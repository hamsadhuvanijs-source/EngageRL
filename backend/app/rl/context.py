from app.models.chat import Chat
from app.models.material_source import MaterialSource

# Coarse context buckets, computed now but not yet used to partition BanditState rows.
# Kept as a seam so a future contextual bandit (e.g. per user+mode+bucket, or a linear
# contextual model) can slot in without changing the ingestion/telemetry/RL surface.

LENGTH_BUCKETS = (
    (2000, "short"),
    (8000, "medium"),
)


def length_bucket(char_count: int) -> str:
    for threshold, label in LENGTH_BUCKETS:
        if char_count <= threshold:
            return label
    return "long"


def build_context(chat: Chat, sources: list[MaterialSource]) -> dict:
    total_chars = sum(s.char_count for s in sources)
    return {
        "length_bucket": length_bucket(total_chars),
        "source_types": sorted({s.source_type for s in sources}),
    }
