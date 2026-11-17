import csv

from loadtest.summary import collect_plateaus, write_markdown, write_svg


def _write_stats(path, users, p50, p95, p99, requests_per_second, requests, failures):
    fields = [
        "Type",
        "Name",
        "Request Count",
        "Failure Count",
        "50%",
        "95%",
        "99%",
        "Requests/s",
    ]
    with path.joinpath(f"users-{users}_stats.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "Type": "POST",
                "Name": "POST /v1/predict",
                "Request Count": requests,
                "Failure Count": failures,
                "50%": p50,
                "95%": p95,
                "99%": p99,
                "Requests/s": requests_per_second,
            }
        )


def test_collect_plateaus_and_mark_slo(tmp_path):
    _write_stats(tmp_path, 10, 40, 100, 150, 8, 480, 0)
    _write_stats(tmp_path, 50, 70, 220, 400, 12, 720, 1)

    plateaus = collect_plateaus(tmp_path)
    output = tmp_path / "summary.md"
    write_markdown(plateaus, output, 200)

    assert plateaus[0].under_slo
    assert not plateaus[1].under_slo
    content = output.read_text(encoding="utf-8")
    assert "Capacité sous le SLO : **8.00 req/s**" in content
    assert "Premier palier hors SLO : **50 utilisateurs**" in content

    graph = tmp_path / "summary.svg"
    write_svg(plateaus, graph, 200)
    graph_content = graph.read_text(encoding="utf-8")
    assert "utilisateurs simultanés" in graph_content
    assert "Débit (req/s)" in graph_content
    assert "p95 (ms)" in graph_content
    assert "<rect" in graph_content
    assert "SLO p95 &lt; 200 ms" in graph_content
