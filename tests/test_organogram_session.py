"""OG6/OG8 durable original contexts, producer retries and fresh continuation."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from examples.organogram_conformance import REFERENCE, ROOT, canonical_hash, scenario_for
from solvefinite.f8 import IndexBinding
from solvefinite.field_agent import ORGANOGRAM_POLICY
from solvefinite.live import LiveConfig, LiveProtocolError, LiveSession, PROTOCOL, load_live
from solvefinite.runtime import write_json
from solvefinite.session import Scenario, load_session, run_session
from solvefinite.tomigidt import Tomigidt


def observe_request(response, observations=None):
    frame=response["next"]
    return {"protocol":PROTOCOL,"type":"observe","producer":response["producer"],
            "epoch":response["epoch"],"seq":frame["seq"],"position":frame["position"],
            "geometry_epoch":frame["geometry_epoch"],
            "observations":dict.fromkeys(frame["paths"],0) if observations is None else observations}


def advance_reference(live, first=0, stop=9):
    response=live.ready();sent=[]
    for expected in REFERENCE["default_mission"]["events"][first:stop]:
        request=observe_request(response,expected["input"]);sent.append(deepcopy(request))
        response=live.handle(request)
        actual=response["event"]
        if (actual["decision"]["kind"],actual["output"],actual["energy"])!=(
                expected["kind"],expected["state"]["pair"],expected["state"]["energy"]):
            raise AssertionError((actual,expected))
    return response,sent


class OrganogramSessionTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory(prefix="organogram-session-")
        self.addCleanup(temporary.cleanup);self.directory=Path(temporary.name)
        self.path=self.directory/"retained state.json"

    def test_fixed_topology_simulator_still_distinguishes_semantic_epochs(self):
        configured=scenario_for()
        self.assertEqual(configured.observe("k:0:4",2),REFERENCE["default_mission"]["events"][1]["input"])
        self.assertEqual(configured.observe("k:3:2",6,geometry_epoch=1),
                         REFERENCE["default_mission"]["events"][5]["input"])
        self.assertEqual(configured.observe("k:0:3",8,geometry_epoch=1)["k:0:3"],0)
        self.assertEqual(configured.observe("k:0:3",8,geometry_epoch=0)["k:0:3"],70)
        for invalid in (-1,2,True,1.0,"1",None):
            with self.subTest(epoch=invalid),self.assertRaises(ValueError):
                configured.observe("k:0:0",1,geometry_epoch=invalid)

    def test_split_session_preserves_original_context_and_readonly_inspection(self):
        configuration=self.directory/"scenario.json";write_json(configuration,scenario_for().to_dict())
        repaired=run_session(self.path,steps=4,capacity=1,scenario_path=configuration)
        self.assertEqual((repaired["status"],repaired["cycle"]),("GROWTH_PENDING",4))
        grown=run_session(self.path,steps=1,capacity=3,index_binding=IndexBinding(3,-1,17))
        self.assertEqual((grown["cycle"],grown["state"]["geometry_epoch"],grown["state"]["energy"]),(5,1,85))
        complete=run_session(self.path,steps=32,capacity=1)
        self.assertEqual((complete["status"],complete["cycle"],complete["state"]["energy"]),("COMPLETE",9,76))
        configured,restored=load_session(self.path,capacity=12)
        try:
            self.assertEqual(configured,scenario_for())
            self.assertEqual(f"{restored.agent_pair:016X}","860006BA16000646")
            self.assertEqual((restored.manifest.world.width,restored.current_recipe.width),(4,4))
            stage=restored.current_recipe.to_dict()["stages"][0]
            self.assertEqual((stage["tick"],stage["prefix_sha256"]),(5,canonical_hash(restored.events[:4])))
            before=self.path.read_bytes();noop=run_session(self.path,steps=32)
            self.assertEqual(noop["executed_cycles"],0);self.assertEqual(self.path.read_bytes(),before)
        finally:restored.close()

    def test_two_generations_retain_distinct_original_contexts(self):
        expected=REFERENCE["two_epoch_mission"]
        configuration=self.directory/"two epochs.json";write_json(configuration,scenario_for(expected).to_dict())
        result=run_session(self.path,steps=64,scenario_path=configuration)
        self.assertEqual((result["status"],result["cycle"],result["state"]["geometry_epoch"],
                          result["state"]["energy"]),("COMPLETE",14,2,66))
        _,restored=load_session(self.path)
        try:
            grows=[e for e in restored.events if e["growth"] is not None]
            stages=restored.current_recipe.to_dict()["stages"]
            self.assertEqual([s["tick"] for s in stages],[e["cycle"] for e in expected["events"] if e["kind"]=="GROW"])
            for stage,event in zip(stages,grows):
                self.assertEqual(stage["prefix_sha256"],canonical_hash(restored.events[:event["seq"]-1]))
            self.assertNotEqual(stages[0]["prefix_sha256"],stages[1]["prefix_sha256"])
        finally:restored.close()

    def test_live_stale_epoch_is_rejected_even_when_topology_and_locality_match(self):
        with LiveSession(self.path,config=LiveConfig(scenario_for().manifest,producer="local",epoch=12)) as live:
            response,sent=advance_reference(live,stop=5)
            self.assertEqual((response["epoch"],response["next"]["geometry_epoch"]),(12,1))
            self.assertEqual(response["next"]["position"],"k:3:2")
            before=self.path.read_bytes();valid=observe_request(response)
            for invalid in (-1,0,2,True,1.0,"1",None):
                damaged=deepcopy(valid);damaged["geometry_epoch"]=invalid
                with self.subTest(epoch=invalid),self.assertRaises(LiveProtocolError) as caught:
                    live.handle(damaged)
                self.assertEqual(caught.exception.code,"GEOMETRY_EPOCH")
            missing=deepcopy(valid);missing.pop("geometry_epoch")
            far=deepcopy(valid);far["observations"]["k:0:0"]=0
            for request in (missing,far):
                with self.assertRaises(LiveProtocolError):live.handle(request)
            for request in sent:self.assertTrue(live.handle(request)["duplicate"])
            wrong_duplicate=deepcopy(sent[-1]);wrong_duplicate["geometry_epoch"]=1
            with self.assertRaises(LiveProtocolError):live.handle(wrong_duplicate)
            self.assertEqual(self.path.read_bytes(),before)
        with LiveSession(self.path,capacity=1,index_binding=IndexBinding(11,-1,0)) as reopened:
            for request in sent:self.assertTrue(reopened.handle(request)["duplicate"])
            final,later=advance_reference(reopened,first=5)
            self.assertEqual((final["state"]["cycle"],final["state"]["energy"]),(9,76))
            self.assertIsNone(final["next"])
            self.assertTrue(reopened.handle(later[0])["duplicate"])

    def test_fresh_frames_and_new_hazards_cannot_replace_grammar_or_world(self):
        with LiveSession(self.path,config=LiveConfig(scenario_for().manifest)) as live:
            response,_=advance_reference(live,stop=4)
            waiting=live.handle(observe_request(response,{}))
            self.assertEqual((waiting["event"]["decision"]["kind"],waiting["state"]["geometry_epoch"]),("WAIT",0))
            grown=live.handle(observe_request(waiting))
            self.assertEqual(grown["state"]["current_recipe"]["stages"][0]["tick"],6)
            before=grown["state"]["current_recipe"]
            waiting=live.handle(observe_request(grown,{}))
            self.assertEqual(waiting["event"]["decision"]["kind"],"WAIT")
            request=observe_request(waiting);request["observations"][request["position"]]=19
            moved=live.handle(request)
            self.assertEqual(moved["event"]["geometry_epoch"],1)
            self.assertEqual(moved["state"]["current_recipe"],before)
            bad=observe_request(moved);bad["organogram"]={}
            with self.assertRaises(LiveProtocolError):live.handle(bad)

    def test_pure_candidate_rejection_can_retry_same_producer_sequence(self):
        with LiveSession(self.path,config=LiveConfig(scenario_for().manifest)) as live:
            response,_=advance_reference(live,stop=4)
            request=observe_request(response,REFERENCE["default_mission"]["events"][4]["input"])
            before=self.path.read_bytes()
            with patch.object(Tomigidt,"step",side_effect=ValueError("candidate certificate rejected")):
                with self.assertRaisesRegex(ValueError,"certificate"):live.handle(request)
            self.assertEqual(self.path.read_bytes(),before)
            self.assertEqual(live.ready()["state"],response["state"])
            self.assertEqual(live.handle(request)["event"]["decision"]["kind"],"GROW")

    def test_uncertain_or_committed_failure_forces_reopen_before_acknowledgement(self):
        original=Tomigidt.step
        class CommittedFailure(RuntimeError):committed=True
        for committed in (False,True):
            with self.subTest(committed=committed):
                path=self.directory/f"step-{committed}.json"
                with LiveSession(path,config=LiveConfig(scenario_for().manifest)) as live:
                    response,_=advance_reference(live,stop=4)
                    request=observe_request(response,REFERENCE["default_mission"]["events"][4]["input"])
                    before=path.read_bytes()
                    def failing(agent,observations):
                        if committed:
                            original(agent,observations);raise CommittedFailure("committed cleanup")
                        agent.close();raise RuntimeError("uncertain device")
                    with patch.object(Tomigidt,"step",failing),patch("solvefinite.live.write_json") as save:
                        with self.assertRaises(RuntimeError):live.handle(request)
                        save.assert_not_called()
                    with self.assertRaisesRegex(RuntimeError,"failed"):live.ready()
                    self.assertEqual(path.read_bytes(),before)
                with LiveSession(path) as reopened:
                    self.assertEqual(reopened.ready()["state"]["cycle"],4)
                    self.assertFalse(reopened.handle(request)["duplicate"])

    def test_save_failure_resolves_actual_original_prefix_without_double_generation(self):
        for after_replace in (False,True):
            with self.subTest(after_replace=after_replace):
                path=self.directory/f"save-{after_replace}.json"
                with LiveSession(path,config=LiveConfig(scenario_for().manifest)) as live:
                    response,_=advance_reference(live,stop=4)
                    request=observe_request(response,REFERENCE["default_mission"]["events"][4]["input"])
                    def failing_write(target,value):
                        if after_replace:write_json(target,value)
                        raise OSError("uncertain durable save")
                    with patch("solvefinite.live.write_json",failing_write):
                        with self.assertRaises(OSError):live.handle(request)
                    with self.assertRaisesRegex(RuntimeError,"failed"):live.ready()
                with LiveSession(path) as reopened:
                    result=reopened.handle(request)
                    self.assertEqual(result["duplicate"],after_replace)
                    self.assertEqual((result["state"]["cycle"],result["state"]["geometry_epoch"],
                                      result["state"]["energy"]),(5,1,85))
                _,agent=load_live(path)
                try:
                    self.assertEqual(len(agent.current_recipe.to_dict()["stages"]),1)
                    self.assertEqual(agent.current_recipe.to_dict()["stages"][0]["prefix_sha256"],
                                     canonical_hash(agent.events[:4]))
                finally:agent.close()

    def test_cli_exports_and_continues_organogram_profile(self):
        configured,live_config=self.directory/"scenario.json",self.directory/"live.json"
        commands=[
            ["scenario","--profile","organogram","--output",str(configured)],
            ["live-config","--profile","organogram","--output",str(live_config)],
            ["run","--state",str(self.path),"--scenario",str(configured),"--steps","4"],
            ["run","--state",str(self.path),"--steps","32","--index-sign","-1"],
            ["inspect",str(self.path),"--index-phase-origin","99"],
        ]
        for command in commands:
            completed=subprocess.run([sys.executable,"-m","solvefinite","agent",*command],
                                     cwd=ROOT,text=True,capture_output=True,timeout=90)
            self.assertEqual(completed.returncode,0,completed.stderr)
        final=json.loads(completed.stdout)
        self.assertEqual((final["state"]["geometry_epoch"],final["state"]["energy"]),(1,76))
        self.assertEqual(json.loads(live_config.read_text())["agent"]["policy"],ORGANOGRAM_POLICY)
        self.assertNotIn("scale_exponent",final["state"])


@unittest.skipUnless(importlib.util.find_spec("wgpu") is not None,"Optional wgpu is not installed")
class RealOrganogramContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from solvefinite.gpu import GpuUnavailable
        try:probe=Tomigidt(scenario_for().manifest,backend="gpu")
        except GpuUnavailable as exc:raise unittest.SkipTest(str(exc)) from exc
        probe.close()

    def fresh_process(self,path,backend,steps):
        result=subprocess.run([sys.executable,"-m","solvefinite","agent","run","--state",str(path),
                               "--backend",backend,"--steps",str(steps),"--capacity","1",
                               "--index-sign","-1","--index-phase-origin","67"],
                              cwd=ROOT,text=True,capture_output=True,timeout=180)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_fresh_process_crossovers_on_each_side_of_admitted_generation(self):
        with TemporaryDirectory(prefix="organogram-crossover-") as temporary:
            folder=Path(temporary);configured=folder/"scenario.json";write_json(configured,scenario_for().to_dict())
            archives=[]
            for source,target in (("cpu","gpu"),("gpu","cpu")):
                for cut in (4,5):
                    path=folder/f"{source}-{cut}.json"
                    run_session(path,steps=cut,scenario_path=configured,backend=source)
                    final=self.fresh_process(path,target,64)
                    self.assertEqual((final["status"],final["cycle"],final["state"]["energy"]),("COMPLETE",9,76))
                    archives.append(json.loads(path.read_text())["agent"])
            self.assertTrue(all(value==archives[0] for value in archives[1:]))

    def test_fresh_process_preserves_generated_world_defer_and_original_tick(self):
        with TemporaryDirectory(prefix="organogram-defer-") as temporary:
            folder=Path(temporary);configured=folder/"scenario.json"
            write_json(configured,scenario_for(max_search_expansions=7).to_dict());archives=[]
            for source,target in (("cpu","gpu"),("gpu","cpu")):
                path=folder/f"{source}.json"
                value=run_session(path,steps=1,scenario_path=configured,backend=source)
                for _ in range(512):
                    if value["state"]["geometry_epoch"]==1 and value["status"]=="SEARCH_DEFERRED":break
                    value=run_session(path,steps=1,backend=source)
                else:self.fail("No generated-world DEFER observed")
                original_tick=value["state"]["current_recipe"]["stages"][0]["tick"]
                self.assertNotEqual(original_tick,5)
                final=self.fresh_process(path,target,2000)
                self.assertEqual(final["status"],"COMPLETE")
                self.assertEqual(final["state"]["current_recipe"]["stages"][0]["tick"],original_tick)
                archives.append(json.loads(path.read_text())["agent"])
            self.assertEqual(archives[0],archives[1])


if __name__=="__main__":
    unittest.main()
