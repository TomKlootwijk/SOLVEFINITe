"""PX1-PX2: exact local eigen-axes of a Klein scalar-field stencil.

The operator is the rank-one structure tensor ``g g^T`` of the unscaled
centered difference. These axes describe the finite indexing profile; they
do not supply a global eigenmode or replace geometric adjacency.
"""

from dataclasses import dataclass
from math import gcd

from .klein import KleinDomain
from .runtime import _integer


def _sign(value: object) -> int:
    if type(value) is not int or value not in (-1, 1):
        raise ValueError("psi_sign must be exactly -1 or +1")
    return value


@dataclass(frozen=True, slots=True)
class PsiAxis:
    """An immutable exact eigenpair, including its stencil and operator.

    The vector retains the selected global sign. At a zero gradient the
    declared degenerate choice is either sign of the local u axis.
    """

    gradient: tuple[int, int]
    tensor: tuple[int, int, int, int]
    eigenvalue: int
    vector: tuple[int, int]
    degenerate: bool

    def __post_init__(self) -> None:
        for values, length, low, high, label in (
                (self.gradient, 2, -2, 2, "gradient"),
                (self.tensor, 4, -4, 4, "tensor"),
                (self.vector, 2, -2, 2, "vector")):
            if type(values) is not tuple or len(values) != length:
                raise ValueError(f"{label} must be an immutable {length}-tuple")
            for value in values:
                _integer(value, low, high, label)
        _integer(self.eigenvalue, 0, 8, "eigenvalue")
        if type(self.degenerate) is not bool:
            raise ValueError("degenerate must be a Boolean")
        gu, gv = self.gradient
        if self.tensor != (gu * gu, gu * gv, gv * gu, gv * gv):
            raise ValueError("Tensor must be the outer product of the gradient")
        if self.eigenvalue != gu * gu + gv * gv:
            raise ValueError("Eigenvalue must be the squared gradient length")
        divisor = gcd(abs(gu), abs(gv))
        if self.degenerate != (divisor == 0):
            raise ValueError("Degeneracy must agree with the zero gradient")
        primitive = (gu // divisor, gv // divisor) if divisor else (1, 0)
        if self.vector not in (primitive, tuple(-value for value in primitive)):
            raise ValueError("Vector must be a signed primitive axis with the declared fallback")

    def transport(self, orientation: int) -> "PsiAxis":
        """Express this axis in the same or reflected local chart.

        This is a frame transformation at the same point, not a claim that
        the stencil at an adjacent point has the same eigenstructure.
        """
        _integer(orientation, 0, 1, "orientation")
        sign = -1 if orientation else 1
        gu, gv = self.gradient
        a, b, c, d = self.tensor
        pu, pv = self.vector
        return PsiAxis((gu, sign * gv), (a, sign * b, sign * c, d),
                       self.eigenvalue, (pu, sign * pv), self.degenerate)


def axis_from_gradient(gu: int, gv: int, psi_sign: int = 1) -> PsiAxis:
    """Choose the exact largest eigenpair and explicit zero-eigenspace tie."""
    _integer(gu, -2, 2, "gradient u")
    _integer(gv, -2, 2, "gradient v")
    psi_sign = _sign(psi_sign)
    divisor = gcd(abs(gu), abs(gv))
    primitive = (gu // divisor, gv // divisor) if divisor else (1, 0)
    return PsiAxis(
        (gu, gv), (gu * gu, gu * gv, gv * gu, gv * gv), gu * gu + gv * gv,
        tuple(psi_sign * value for value in primitive), divisor == 0,
    )


def field_axes(domain: KleinDomain, fields: object, psi_sign: int = 1) -> tuple[PsiAxis, ...]:
    """Derive every canonical-frame axis from a bounded scalar field.

    This verifies strict field values and signed unit-edge Lipschitz bounds.
    The caller separately certifies that the field is the requested exact
    SDF; satisfying these local bounds alone does not establish that claim.
    """
    if type(domain) is not KleinDomain:
        raise ValueError("domain must be a KleinDomain")
    psi_sign = _sign(psi_sign)
    if type(fields) not in (tuple, list) or len(fields) != len(domain.nodes):
        raise ValueError("fields require one integer scalar per domain node")
    values = tuple(fields)
    for value in values:
        _integer(value, -127, 127, "field value")
    if any(abs(values[source] - values[target]) > 1 for source, target, _ in domain.edges):
        raise ValueError("Field violates the signed unit-edge Lipschitz bound")
    result = []
    for node in range(len(domain.nodes)):
        up, um, vp, vm = (domain.step(node, direction)[0]
                          for direction in ("u+", "u-", "v+", "v-"))
        result.append(axis_from_gradient(values[up] - values[um],
                                         values[vp] - values[vm], psi_sign))
    return tuple(result)
