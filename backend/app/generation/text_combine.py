from app.models.material_source import MaterialSource

PER_SOURCE_BUDGET = 6000
TOTAL_BUDGET = 12000


def combine_source_text(
    sources: list[MaterialSource], per_source_budget: int = PER_SOURCE_BUDGET, total_budget: int = TOTAL_BUDGET
) -> str:
    blocks = []
    for source in sources:
        if source.status != "extracted" or not source.raw_text:
            continue
        header = f"## Source: {source.original_ref} ({source.source_type})"
        blocks.append(f"{header}\n{source.raw_text[:per_source_budget]}")

    combined = "\n\n".join(blocks)
    return combined[:total_budget]
