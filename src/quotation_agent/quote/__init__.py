"""报价链路：blocks → CanonicalRFQ → 定价 → 审批 → mart_rfq。"""

from .build import build_quote, load_blocks, render_text, requested_discount  # noqa: F401
from .model import (  # noqa: F401
    Approval,
    CanonicalLine,
    CanonicalRFQ,
    Conflict,
    HeldLine,
    PricedLine,
    Quote,
    RawLine,
    Trace,
)
from .normalise import candidates_from_blocks, merge, parse_qty, parse_tol  # noqa: F401
from .pricing import (  # noqa: F401
    APPROVAL_TOTAL_THRESHOLD,
    MARGIN,
    POLICY_MAX_DISCOUNT,
    discount_rate,
    machine_rate,
    material_price,
    price_line,
)
