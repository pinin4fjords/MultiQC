import io
import logging
import os
from typing import Dict, List, Union, Tuple, Optional, Literal, Any

import math
import plotly.graph_objects as go
from pydantic import Field

from multiqc.plots.plotly.plot import PlotType, BaseDataset, Plot, PConfig
from multiqc import config, report
from multiqc.utils.util_functions import update_dict

logger = logging.getLogger(__name__)


class LinePlotConfig(PConfig):
    xlab: Optional[str] = None
    ylab: Optional[str] = None
    categories: bool = False
    smooth_points: Optional[int] = None
    smooth_points_sumcounts: Union[bool, List[bool], None] = None
    extra_series: Union[Dict[str, Any], List[Dict[str, Any]], List[List[Dict[str, Any]]], None] = None
    xMinRange: Optional[Union[float, int]] = Field(None, deprecated="x_minrange")
    yMinRange: Optional[Union[float, int]] = Field(None, deprecated="y_minrange")
    x_minrange: Optional[Union[float, int]] = None
    y_minrange: Optional[Union[float, int]] = None
    xPlotBands: Optional[List[Dict[str, Union[float, int, str]]]] = Field(None, deprecated="x_bands")
    yPlotBands: Optional[List[Dict[str, Union[float, int, str]]]] = Field(None, deprecated="y_bands")
    xPlotLines: Optional[List[Dict[str, Union[float, int, str]]]] = Field(None, deprecated="x_lines")
    yPlotLines: Optional[List[Dict[str, Union[float, int, str]]]] = Field(None, deprecated="y_lines")
    x_bands: Optional[List[Dict[str, Union[float, int, str]]]] = None
    y_bands: Optional[List[Dict[str, Union[float, int, str]]]] = None
    x_lines: Optional[List[Dict[str, Union[float, int, str]]]] = None
    y_lines: Optional[List[Dict[str, Union[float, int, str]]]] = None
    style: Literal["lines", "lines+markers"] = "lines"
    hide_zero_cats: Optional[bool] = Field(False, deprecated="hide_empty")
    hide_empty: bool = False
    colors: Dict[str, str] = {}


# {"name": "SAMPLE1", "color": "#111111", "data": [[x, y], [x, y], ...]}
LineT = Dict[str, Union[str, List[Tuple[Union[float, int, str], Union[float, int]]]]]


def plot(lists_of_lines: List[List[LineT]], pconfig: LinePlotConfig) -> "LinePlot":
    """
    Build and add the plot data to the report, return an HTML wrapper.
    :param lists_of_lines: each dataset is a 2D dict, first keys as sample names, then x:y data pairs
    :param pconfig: dict with config key:value pairs. See CONTRIBUTING.md
    :return: HTML with JS, ready to be inserted into the page
    """

    # if self.n_samples >= config.max_table_rows:
    # Get a line of median values at each point with an interval of max and
    # min values
    # Create a violin of median values in each sample, showing dots for outliers
    # Clicking on a dot of a violin will show the line plot for that sample

    return LinePlot.create(pconfig, lists_of_lines)


class Dataset(BaseDataset):
    lines: List[Dict]

    @staticmethod
    def create(
        dataset: BaseDataset,
        lines: List[Dict],
        pconfig: LinePlotConfig,
    ) -> "Dataset":
        dataset: Dataset = Dataset(
            **dataset.model_dump(),
            lines=lines,
        )

        # Prevent Plotly from parsing strings as numbers
        if pconfig.categories or dataset.dconfig.get("categories"):
            dataset.layout["xaxis"]["type"] = "category"

        # convert HighCharts-style hardcoded trace parameters to Plotly style
        lines = []
        for src_line in dataset.lines:
            new_line = {
                "name": src_line["name"],
                "data": src_line["data"],
                "color": src_line.get("color"),
                "showlegend": src_line.get("showlegend", src_line.get("showInLegend", True)),
                "line": {
                    "dash": convert_dash_style(src_line.get("dash", src_line.get("dashStyle"))),
                    "width": src_line.get("line", {}).get("width", src_line.get("lineWidth")),
                },
            }
            if "marker" in src_line:
                new_line["mode"] = "lines+markers"
                new_line["marker"] = {
                    "symbol": src_line["marker"].get("symbol"),
                    "line": {
                        "width": src_line["marker"].get("line", {}).get("width", src_line["marker"].get("lineWidth")),
                        "color": src_line["marker"].get("line", {}).get("color", src_line["marker"].get("lineColor")),
                    },
                }
            lines.append(remove_nones_and_empty_dicts(new_line))

        dataset.lines = lines

        mode = pconfig.style
        if config.lineplot_style == "lines+markers":
            mode = "lines+markers"

        dataset.trace_params.update(
            mode=mode,
            line={"width": 2},
        )
        if mode == "lines+markers":
            dataset.trace_params.update(
                line={"width": 0.6},
                marker={"size": 5},
            )
        return dataset

    def create_figure(
        self,
        layout: go.Layout,
        is_log=False,
        is_pct=False,
        **kwargs,
    ) -> go.Figure:
        """
        Create a Plotly figure for a dataset
        """
        if layout.showlegend is True:
            # Extra space for legend
            layout.height += len(self.lines) * 5

        fig = go.Figure(layout=layout)
        for line in self.lines:
            xs = [x[0] for x in line["data"]]
            ys = [x[1] for x in line["data"]]
            params = dict(
                marker=line.get("marker", {}),
                line=line.get("line", {}),
                showlegend=line.get("showlegend", None),
                mode=line.get("mode", None),
            )
            params = update_dict(params, self.trace_params, none_only=True)
            params["marker"]["color"] = line.get("color")

            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    name=line["name"],
                    text=[line["name"]] * len(xs),
                    **params,
                )
            )
        return fig

    def save_data_file(self) -> None:
        y_by_x_by_sample = dict()
        last_cats = None
        shared_cats = True
        for line in self.lines:
            y_by_x_by_sample[line["name"]] = dict()

            # Check to see if all categories are the same
            if len(line["data"]) > 0 and isinstance(line["data"][0], list):
                if last_cats is None:
                    last_cats = [x[0] for x in line["data"]]
                elif last_cats != [x[0] for x in line["data"]]:
                    shared_cats = False

            for i, x in enumerate(line["data"]):
                if isinstance(x, list):
                    y_by_x_by_sample[line["name"]][x[0]] = x[1]
                else:
                    try:
                        y_by_x_by_sample[line["name"]][self.dconfig["categories"][i]] = x
                    except (ValueError, KeyError, IndexError):
                        y_by_x_by_sample[line["name"]][str(i)] = x

        # Custom tsv output if the x-axis varies
        if not shared_cats and config.data_format in ["tsv", "csv"]:
            sep = "\t" if config.data_format == "tsv" else ","
            fout = ""
            for line in self.lines:
                fout += line["name"] + sep + "X" + sep + sep.join([str(x[0]) for x in line["data"]]) + "\n"
                fout += line["name"] + sep + "Y" + sep + sep.join([str(x[1]) for x in line["data"]]) + "\n"

            fn = f"{self.uid}.{config.data_format_extensions[config.data_format]}"
            fpath = os.path.join(report.data_tmp_dir(), fn)
            with io.open(fpath, "w", encoding="utf-8") as f:
                f.write(fout.encode("utf-8", "ignore").decode("utf-8"))
        else:
            report.write_data_file(y_by_x_by_sample, self.uid)


class LinePlot(Plot):
    datasets: List[Dataset]

    @staticmethod
    def create(
        pconfig: LinePlotConfig,
        lists_of_lines: List[List[LineT]],
    ) -> "LinePlot":
        max_n_samples = max(len(x) for x in lists_of_lines) if len(lists_of_lines) > 0 else 0

        model = Plot.initialize(
            plot_type=PlotType.LINE,
            pconfig=pconfig,
            n_datasets=len(lists_of_lines),
            n_samples=max_n_samples,
            axis_controlled_by_switches=["yaxis"],
            default_tt_label="<br>%{x}: %{y}",
        )

        # Very large legend for automatically enabled flat plot mode is not very helpful
        if pconfig.showlegend is None and max_n_samples > 250:
            model.layout.showlegend = False

        model.datasets = [Dataset.create(d, lines, pconfig) for d, lines in zip(model.datasets, lists_of_lines)]

        # Make a tooltip always show on hover over any point on plot
        model.layout.hoverdistance = -1

        y_minrange = pconfig.y_minrange
        x_minrange = pconfig.x_minrange
        y_bands = pconfig.y_bands
        x_bands = pconfig.x_bands
        x_lines = pconfig.x_lines
        y_lines = pconfig.y_lines
        if y_minrange or y_bands or y_lines:
            # We don't want the bands to affect the calculated axis range, so we
            # find the min and the max from data points, and manually set the range.
            for dataset in model.datasets:
                minval = dataset.layout["yaxis"]["autorangeoptions"]["minallowed"]
                maxval = dataset.layout["yaxis"]["autorangeoptions"]["maxallowed"]
                for line in dataset.lines:
                    ys = [x[1] for x in line["data"]]
                    if len(ys) > 0:
                        minval = min(ys) if minval is None else min(minval, min(ys))
                        maxval = max(ys) if maxval is None else max(maxval, max(ys))
                if maxval is not None and minval is not None:
                    maxval += (maxval - minval) * 0.05
                clipmin = dataset.layout["yaxis"]["autorangeoptions"]["clipmin"]
                clipmax = dataset.layout["yaxis"]["autorangeoptions"]["clipmax"]
                if clipmin is not None and minval is not None and clipmin > minval:
                    minval = clipmin
                if clipmax is not None and maxval is not None and clipmax < maxval:
                    maxval = clipmax
                if y_minrange is not None and maxval is not None and minval is not None:
                    maxval = max(maxval, minval + y_minrange)
                if model.layout.yaxis.type == "log":
                    minval = math.log10(minval) if minval is not None and minval > 0 else None
                    maxval = math.log10(maxval) if maxval is not None and maxval > 0 else None
                dataset.layout["yaxis"]["range"] = [minval, maxval]

        if not pconfig.categories and x_minrange or x_bands or x_lines:
            # same as above but for x-axis
            for dataset in model.datasets:
                minval = dataset.layout["xaxis"]["autorangeoptions"]["minallowed"]
                maxval = dataset.layout["xaxis"]["autorangeoptions"]["maxallowed"]
                for line in dataset.lines:
                    xs = [x[0] for x in line["data"]]
                    if len(xs) > 0:
                        minval = min(xs) if minval is None else min(minval, min(xs))
                        maxval = max(xs) if maxval is None else max(maxval, max(xs))
                clipmin = dataset.layout["xaxis"]["autorangeoptions"]["clipmin"]
                clipmax = dataset.layout["xaxis"]["autorangeoptions"]["clipmax"]
                if clipmin is not None and minval is not None and clipmin > minval:
                    minval = clipmin
                if clipmax is not None and maxval is not None and clipmax < maxval:
                    maxval = clipmax
                if x_minrange is not None and maxval is not None and minval is not None:
                    maxval = max(maxval, minval + x_minrange)
                if model.layout.xaxis.type == "log":
                    minval = math.log10(minval) if minval is not None and minval > 0 else None
                    maxval = math.log10(maxval) if maxval is not None and maxval > 0 else None
                dataset.layout["xaxis"]["range"] = [minval, maxval]

        model.layout.shapes = (
            [
                dict(
                    type="rect",
                    y0=band["from"],
                    y1=band["to"],
                    x0=0,
                    x1=1,
                    xref="paper",  # make x coords are relative to the plot paper [0,1]
                    fillcolor=band["color"],
                    line={
                        "width": 0,
                    },
                    layer="below",
                )
                for band in (y_bands or [])
            ]
            + [
                dict(
                    type="rect",
                    x0=band["from"],
                    x1=band["to"],
                    y0=0,
                    y1=1,
                    yref="paper",  # make y coords are relative to the plot paper [0,1]
                    fillcolor=band["color"],
                    line={
                        "width": 0,
                    },
                    layer="below",
                )
                for band in (x_bands or [])
            ]
            + [
                dict(
                    type="line",
                    xref="paper",
                    yref="y",
                    x0=0,
                    y0=line["value"],
                    x1=1,
                    y1=line["value"],
                    line={
                        "width": line.get("width", 2),
                        "dash": convert_dash_style(line.get("dash", line.get("dashStyle"))),
                        "color": line["color"],
                    },
                )
                for line in (y_lines or [])
            ]
            + [
                dict(
                    type="line",
                    yref="paper",
                    xref="x",
                    x0=line["value"],
                    y0=0,
                    x1=line["value"],
                    y1=1,
                    line={
                        "width": line.get("width", 2),
                        "dash": convert_dash_style(line.get("dash", line.get("dashStyle"))),
                        "color": line["color"],
                    },
                )
                for line in (x_lines or [])
            ]
        )

        return LinePlot(**model.__dict__)


def convert_dash_style(dash_style: str) -> str:
    """Convert dash style from Highcharts to Plotly"""
    mapping = {
        "Solid": "solid",
        "ShortDash": "dash",
        "ShortDot": "dot",
        "ShortDashDot": "dashdot",
        "ShortDashDotDot": "dashdot",
        "Dot": "dot",
        "Dash": "dash",
        "DashDot": "dashdot",
        "LongDash": "longdash",
        "LongDashDot": "longdashdot",
        "LongDashDotDot": "longdashdot",
    }
    if dash_style in mapping.values():  # Plotly style?
        return dash_style
    elif dash_style in mapping.keys():  # Highcharts style?
        return mapping[dash_style]
    return "solid"


def remove_nones_and_empty_dicts(d: Dict) -> Dict:
    """Remove None and empty dicts from a dict recursively."""
    if not isinstance(d, Dict):
        return d
    return {k: remove_nones_and_empty_dicts(v) for k, v in d.items() if v is not None and v != {}}
