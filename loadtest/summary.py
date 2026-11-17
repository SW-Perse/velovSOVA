"""Agrège les résultats Locust et produit le bilan de saturation."""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Plateau:
    """Mesures agrégées pour un nombre d'utilisateurs donné."""

    users: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    requests_per_second: float
    error_rate: float

    @property
    def under_slo(self) -> bool:
        """Indique si le plateau respecte le SLO de latence et d'erreurs."""
        return self.p95_ms < 200 and self.error_rate < 0.001


def _number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "").strip()
    if not value:
        raise ValueError(f"Colonne Locust absente ou vide : {key}")
    return float(value.replace(",", "."))


def read_plateau(path: Path) -> Plateau:
    """Lit la ligne Aggregated d'un fichier Locust *_stats.csv."""
    match = re.search(r"users-(\d+)_stats\.csv$", path.name)
    if match is None:
        raise ValueError(f"Nom de fichier de plateau invalide : {path.name}")

    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))

    aggregated = next(
        (row for row in rows if row.get("Type") == "Aggregated" or row.get("Name") == "Aggregated"),
        None,
    )
    if aggregated is None and len(rows) == 1:
        aggregated = rows[0]
    if aggregated is None:
        raise ValueError(f"Ligne agrégée absente de {path}")

    requests = _number(aggregated, "Request Count")
    failures = _number(aggregated, "Failure Count")
    error_rate = failures / requests if requests else 1.0
    return Plateau(
        users=int(match.group(1)),
        p50_ms=_number(aggregated, "50%"),
        p95_ms=_number(aggregated, "95%"),
        p99_ms=_number(aggregated, "99%"),
        requests_per_second=_number(aggregated, "Requests/s"),
        error_rate=error_rate,
    )


def collect_plateaus(results_directory: Path) -> list[Plateau]:
    """Collecte et trie les cinq plateaux présents dans un répertoire."""
    paths = sorted(results_directory.glob("users-*_stats.csv"))
    if not paths:
        raise FileNotFoundError(f"Aucun résultat Locust dans {results_directory}")
    return sorted((read_plateau(path) for path in paths), key=lambda plateau: plateau.users)


def _format_error_rate(rate: float) -> str:
    return f"{rate * 100:.3f}%"


def write_markdown(plateaus: list[Plateau], output: Path, slo_ms: float) -> None:
    """Écrit le tableau et la capacité mesurée sous le SLO."""
    passing = [plateau for plateau in plateaus if plateau.p95_ms < slo_ms and plateau.error_rate < 0.001]
    capacity = max(passing, key=lambda plateau: plateau.requests_per_second) if passing else None
    first_failure = next(
        (plateau for plateau in plateaus if plateau.p95_ms >= slo_ms or plateau.error_rate >= 0.001),
        None,
    )

    lines = [
        "# Courbe de saturation",
        "",
        f"SLO : p95 < {slo_ms:.0f} ms et taux d'erreur < 0,1 %.",
        "",
        "| Utilisateurs | p50 (ms) | p95 (ms) | p99 (ms) | Débit (req/s) | Erreurs | SLO |",
        "|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for plateau in plateaus:
        status = "OK" if plateau.p95_ms < slo_ms and plateau.error_rate < 0.001 else "DÉPASSÉ"
        lines.append(
            f"| {plateau.users} | {plateau.p50_ms:.1f} | {plateau.p95_ms:.1f} | "
            f"{plateau.p99_ms:.1f} | {plateau.requests_per_second:.2f} | "
            f"{_format_error_rate(plateau.error_rate)} | {status} |"
        )

    if capacity is None:
        lines.extend(["", "Capacité sous le SLO : aucune capacité mesurée ne respecte le SLO."])
    else:
        lines.extend(
            [
                "",
                f"Capacité sous le SLO : **{capacity.requests_per_second:.2f} req/s** "
                f"au palier de {capacity.users} utilisateurs.",
            ]
        )
    if first_failure is not None:
        lines.append(
            f"Premier palier hors SLO : **{first_failure.users} utilisateurs** "
            f"(p95 {first_failure.p95_ms:.1f} ms, erreurs {_format_error_rate(first_failure.error_rate)})."
        )

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_svg(plateaus: list[Plateau], output: Path, slo_ms: float) -> None:
    """Produit un graphique SVG en barres et courbe à double axe."""
    width, height = 1000, 650
    left, right, top, bottom = 90, 90, 70, 105
    plot_width, plot_height = width - left - right, height - top - bottom
    max_rate = max(plateau.requests_per_second for plateau in plateaus) or 1
    max_latency = max(max(plateau.p99_ms for plateau in plateaus), slo_ms) or 1
    rate_axis_max = max(10, ((max_rate * 1.2) // 10 + 1) * 10)
    latency_axis_max = max(100, ((max_latency * 1.2) // 100 + 1) * 100)
    slot_width = plot_width / len(plateaus)

    def x(index: int) -> float:
        return left + slot_width * (index + 0.5)

    def y_rate(rate: float) -> float:
        return top + plot_height - rate / rate_axis_max * plot_height

    def y_latency(latency: float) -> float:
        return top + plot_height - latency / latency_axis_max * plot_height

    def points(values: list[tuple[float, float]]) -> str:
        return " ".join(f"{px:.1f},{py:.1f}" for px, py in values)

    rate_points = [(x(index), y_rate(item.requests_per_second)) for index, item in enumerate(plateaus)]
    latency_points = [(x(index), y_latency(item.p95_ms)) for index, item in enumerate(plateaus)]
    slo_y = y_latency(slo_ms)
    axis_ticks = 5
    grid = []
    for tick in range(axis_ticks + 1):
        fraction = tick / axis_ticks
        y = top + plot_height - fraction * plot_height
        rate_value = rate_axis_max * fraction
        latency_value = latency_axis_max * fraction
        grid.extend(
            [
                f'<line class="grid" x1="{left}" y1="{y:.1f}" '
                f'x2="{width - right}" y2="{y:.1f}"/>',
                f'<text class="tick left-tick" x="{left - 12}" y="{y + 5:.1f}" '
                f'text-anchor="end">{rate_value:.0f}</text>',
                f'<text class="tick right-tick" x="{width - right + 12}" y="{y + 5:.1f}">'
                f'{latency_value:.0f}</text>',
            ]
        )
    bars = []
    user_labels = []
    rate_labels = []
    latency_labels = []
    bar_width = slot_width * 0.56
    for index, item in enumerate(plateaus):
        center = x(index)
        bar_x = center - bar_width / 2
        bar_y = y_rate(item.requests_per_second)
        bar_height = top + plot_height - bar_y
        bars.append(
            f'<rect class="bar" x="{bar_x:.1f}" y="{bar_y:.1f}" '
            f'width="{bar_width:.1f}" height="{bar_height:.1f}"/>'
        )
        user_labels.append(
            f'<text class="axis-label" x="{center:.1f}" y="{height - 62}" '
            f'text-anchor="middle">{item.users}</text>'
        )
        rate_labels.append(
            f'<text class="value rate-value" x="{center:.1f}" y="{bar_y - 8:.1f}" '
            f'text-anchor="middle">{item.requests_per_second:.2f}</text>'
        )
        latency_labels.append(
            f'<text class="value latency-value" x="{center:.1f}" y="{y_latency(item.p95_ms) - 12:.1f}" '
            f'text-anchor="middle">{item.p95_ms:.0f}</text>'
        )
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<style>"
        "text{font:14px sans-serif;fill:#263238}"
        ".title{font-size:20px;font-weight:bold}"
        ".axis{stroke:#263238;stroke-width:2}"
        ".grid{stroke:#cfd8dc;stroke-width:1}"
        ".bar{fill:#78909c}"
        ".rate{fill:none;stroke:#455a64;stroke-width:4}"
        ".latency{fill:none;stroke:#e67e22;stroke-width:4}"
        ".point{fill:#e67e22;stroke:#fff;stroke-width:2}"
        ".slo{stroke:#c0392b;stroke-width:2;stroke-dasharray:8 6}"
        ".rate-value{fill:#455a64}"
        ".latency-value{fill:#d35400}"
        ".legend{font-size:15px}"
        "</style>",
        f'<text class="title" x="{width / 2}" y="32" text-anchor="middle">'
        "Courbe de saturation de l'API</text>",
        *grid,
        f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}"/>',
        f'<line class="axis" x1="{width - right}" y1="{top}" '
        f'x2="{width - right}" y2="{top + plot_height}"/>',
        f'<line class="axis" x1="{left}" y1="{top + plot_height}" '
        f'x2="{width - right}" y2="{top + plot_height}"/>',
        f'<line class="slo" x1="{left}" y1="{slo_y:.1f}" x2="{width - right}" y2="{slo_y:.1f}"/>',
        f'<text class="slo-label" x="{width - right - 4}" y="{slo_y - 8:.1f}" '
        f'text-anchor="end">SLO p95 &lt; {slo_ms:.0f} ms</text>',
        *bars,
        f'<polyline class="rate" points="{points(rate_points)}"/>',
        f'<polyline class="latency" points="{points(latency_points)}"/>',
        *[f'<circle class="point" cx="{px:.1f}" cy="{py:.1f}" r="5"/>' for px, py in latency_points],
        *rate_labels,
        *latency_labels,
        *user_labels,
        f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle">'
        "Charge : utilisateurs simultanés</text>",
        f'<text x="22" y="{height / 2}" transform="rotate(-90 22 {height / 2})" '
        'text-anchor="middle">Débit (req/s)</text>',
        f'<text x="{width - 22}" y="{height / 2}" '
        f'transform="rotate(90 {width - 22} {height / 2})" text-anchor="middle">p95 (ms)</text>',
        '<rect x="110" y="48" width="18" height="12" class="bar"/>',
        '<text class="legend" x="136" y="59">Débit (req/s)</text>',
        '<line class="latency" x1="275" y1="54" x2="300" y2="54"/>',
        '<circle class="point" cx="287.5" cy="54" r="4"/>',
        '<text class="legend" x="308" y="59">p95 (ms)</text>',
        "</svg>",
    ]
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")


def main() -> None:
    """Point d'entrée de l'agrégateur de campagne."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--slo-ms", type=float, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    plateaus = collect_plateaus(args.results_dir)
    output = args.output or args.results_dir / "saturation-summary.md"
    write_markdown(plateaus, output, args.slo_ms)
    write_svg(plateaus, output.with_suffix(".svg"), args.slo_ms)
    print(output)


if __name__ == "__main__":
    main()
