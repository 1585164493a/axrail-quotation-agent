"""存储层：blob（内容寻址）→ raw 实体 → stage（解析结果）→ mart（业务模型）。"""

from .db import (  # noqa: F401
    INLINE_MAX_BYTES,
    SCHEMA_META,
    SCHEMA_VERSION,
    connect,
    finish_run,
    get_blob,
    init_db,
    put_blob,
    save_blocks,
    save_raw_attachment,
    save_raw_email,
    sha256_file,
    stage_envelope,
    start_run,
    summary,
    update_attachment_parse,
)
