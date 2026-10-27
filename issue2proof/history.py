"""Import verified historical investigation reports into repository memory."""

from .memory import capsule_from_report, save_capsule


def import_verified_reports(records: list[dict], *, key: str | None = None) -> dict:
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError("History import accepts at most 1,000 report records.")
    imported = []
    skipped = []
    for index, report in enumerate(records):
        try:
            if not isinstance(report, dict):
                raise ValueError("Record is not a JSON object.")
            capsule = save_capsule(capsule_from_report(report, key=key))
            imported.append(
                {
                    "record": index,
                    "run_id": capsule["origin"]["run_id"],
                    "capsule_id": capsule["id"],
                    "repository_key": capsule["repository_key"],
                }
            )
        except (KeyError, TypeError, ValueError) as error:
            skipped.append({"record": index, "reason": str(error)})
    return {"imported": imported, "skipped": skipped}
