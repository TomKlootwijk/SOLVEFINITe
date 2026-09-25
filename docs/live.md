# TOMIGIDt live observation channel

`agent serve` keeps one TOMIGIDt owner available for new sensor frames. The
producer supplies local measurements; the agent generates its own routes,
forecasts and actions. WAIT, INSUFFICIENT_ENERGY and pending search do not end
the process. A later frame can let the same owner continue.

This adds live input to the existing declared application profile. Movement
and repair still update simulated RP32 state. No physical device is controlled.
The source PDF's retained-input and admission requirements motivate the
producer/epoch/sequence envelope; this channel is an explicit implementation
binding, not a claim that it implements every LUS or DIGID contract.

## Run and inspect

```sh
python -m solvefinite agent live-config --output output/tomigidt/live-config.json
python -m solvefinite agent serve --config output/tomigidt/live-config.json --state output/tomigidt/live.json
```

The server emits one JSON line immediately, with `type: "ready"`, then reads
one JSON request per line from standard input. Each response is flushed to
standard output. Diagnostics go to standard error. EOF ends the channel and
releases ownership. A process restart with the same state file reconstructs
the same identity, observations, decisions and unfinished search.

```sh
python -m solvefinite agent live-inspect output/tomigidt/live.json --capacity 1
```

Inspection verifies the complete archive without changing it. Existing
`agent run` and `agent inspect` commands retain their prerecorded-scenario
behavior. Live archives use a separate envelope and default state path.

For an automatic external sensor client demonstration, run:

```sh
python examples/live_sensor_demo.py --state output/tomigidt/live-demo.json
```

Use a new state path for each demonstration. This client runs the agent in a
separate process, supplies an incomplete frame, reports high local hazards,
then supplies cleared measurements. It terminates and restarts only its own
agent process after an admitted move, retries the original observation, and
continues to repair. Its report checks that waiting, recovery and duplicate
delivery preserve one decision history. The client supplies no actions or
candidate routes. Its synthetic measurements exercise the channel; they are
not evidence of a physical sensor integration.

## Protocol

The protocol identifier is `tomigidt-live-v1`. The configuration binds one
`producer`, one nonnegative integer `epoch`, and an immutable agent manifest.
Producer names identify a source within this session; they are not credentials.
The default producer is `sensor`, epoch zero, with the current agent policy.
An existing state rejects a different supplied configuration.
An exported default is included at
[examples/tomigidt-live.json](../examples/tomigidt-live.json).

Ready, status, result and recoverable error responses include:

- `protocol`, `producer`, and `epoch` for the retained channel context.
- `state`, the current verified agent snapshot.
- `next`, containing the next `seq`, expected `position`, and local `paths` to
  measure. It is null after mission completion or the declared cycle limit.

An initial full observation for the default root is:

```json
{"protocol":"tomigidt-live-v1","type":"observe","producer":"sensor","epoch":0,"seq":1,"position":"","observations":{"":0,"0":0,"1":0}}
```

Subsequent observations must use the position and sequence in `next`. Every
hazard is a strict integer from 0 through 127. Only the current node and its
outgoing neighbors may be observed. An incomplete frame is valid input and
produces WAIT; older partial frames do not substitute for a fresh full frame.

The accepted result includes:

```text
type: "result"
duplicate: false or true
event: {seq, input, decision, output}
state: current agent snapshot
next: current observation request context, or null
```

`event.input` contains the encoded original observation packets. The decision
contains the agent's route and packed forecast when it moves. `event.output`
is the resulting simulated packed state. No decision or candidate-route fields
are accepted from the producer.

A status request admits no cycle:

```json
{"protocol":"tomigidt-live-v1","type":"status"}
```

Only the exact fields of each request type are accepted. Unknown versions,
wrong producer/epoch, booleans or floats used as sequence or hazard values,
out-of-view observations, duplicate JSON keys and nonfinite numbers are
rejected. Rejected requests do not alter the journal or agent. Ordinary
protocol errors emit `type: "error"`, a `code`, a diagnostic `message`, and the
unchanged current context; the server remains available for a corrected frame.

Each input line is limited to 65,536 characters, including its newline. An
oversized line terminates the channel rather than interpreting its remainder
as a new request. Storage and stream failures also terminate the channel.

## Ordering, acknowledgment and recovery

The source epoch and producer are fixed in the retained configuration. Input
`seq` is the original agent cycle number, starting at one. The new sequence
must be exactly the next cycle; gaps are rejected. Every output-affecting
measurement is retained as an RP32 packet in its original event. The original
observer position is reconstructed from preceding admitted movements.

A result is emitted only after the complete accepted cycle has been saved.
The writer flushes and fsyncs its temporary payload before atomic replacement;
on POSIX it also fsyncs the parent directory. Recovery is tested across process
termination and failed delivery. Storage hardware and filesystem guarantees
still apply; sudden power-loss recovery is not established by these tests.

If the producer did not receive a response, it may resend the **exact original
request**, including its old position, sequence and measurements. The owner
compares it against retained history and returns the original event with
`duplicate: true`. It does not call the policy again, debit energy, advance a
search, or rewrite the archive. A different payload for an admitted sequence
is a conflict. Retrying a much older sequence still returns that original
event, while `state` and `next` describe the agent's current state.

This handles the uncertain boundary where saving succeeded but delivery did
not. A storage error makes the current owner refuse further requests. After
closing it, a new owner replays the actual file to discover whether the cycle
committed. It either returns the recorded result or admits that sequence once.

The OS lock remains held while waiting for input. Another owner of the same
canonical state path is rejected. The archive path cannot be redirected through
the live session's public interface after the lock is acquired. Process exit
releases the lock; a `.lock` file alone says nothing about ownership.
Embedded callers also share one operation lock. Status reads, retries, new
observations and context exit wait for any in-flight save, so they cannot
expose an uncommitted cycle or overwrite a later acknowledged cycle.

Mission completion remains terminal for new observations, but the channel
stays available for status and original-result retries until EOF. Exhausting
the manifest's cycle budget likewise admits no additional cycles. These limits
do not redefine the broader user objective as complete.

The delivery guarantee concerns this session's simulated state transitions.
A physical actuator would need its own acknowledgment and event deduplication
contract. Re-emission of a recorded event is not authorization to execute its
external effect again. Copies of a session are not a global identity registry,
and replay consistency does not authenticate a source or a coordinated edit.

## Verification

Tests exercise strict input admission, unchanged state after rejection,
historical retries after later movement, conflicting sequences, ownership,
source bindings, fresh input after WAIT and insufficient energy, and search
continuation. Actual subprocess tests check flushed output, EOF, termination
after a committed but unread result, new-owner reconstruction and retry.
Injected failures before replacement and after replacement verify both
uncertain-write outcomes. Existing v1 and v2 policy replay remains covered.
