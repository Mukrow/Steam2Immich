import csv

from steam2immich.report_writer import write_dry_run_report


def test_write_dry_run_report_writes_candidate_row(tmp_path, candidate_factory) -> None:
    # Dry-run reports should include headers and candidate details in CSV form.
    candidate = candidate_factory(uncompressed_path=tmp_path / "uncompressed.png")

    report_path = write_dry_run_report([candidate], tmp_path / "reports")

    assert report_path is not None
    with report_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["app_id"] == "1086940"
    assert rows[0]["game_name"] == "Baldur's Gate 3"
    assert rows[0]["using_uncompressed"] == "True"
    assert rows[0]["caption"] == "A dummy Steam screenshot"
