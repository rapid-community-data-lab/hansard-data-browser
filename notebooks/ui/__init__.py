"""
User interface for the Hansard browser/exporter.

The primary aim of this interface is to export a spreadsheet of matching materials
according to the selected parameters.

This uses duckdb querying over the parquet files created from Hansard transcripts. The
user interface allows selection of a set of filters over the materials. This isn't
intended to be an exhaustive set of filters or a comprehensive UI: this is just enough
to satisfy some really common needs, including by:

- speaker/s
- speaker demographics
- party
- time
- procedural titles
- content of the text
- ministerial appointments

All filters operate as of the time the speech was made: so transcriptions from speakers
who changed party will only match for that party during the time they were a member,
not anything they said before or after.

"""

import dataclasses as dc

from tinyhtml import h, raw
import duckdb
import ipywidgets as widgets

# There's one simple query per filter, always returning a set of identifiers to be
# intersected
TEXT_QUERY = """
SELECT para_id
from 'data/paragraph.parquet'
where ? in lower(text)
"""

DATE_QUERY = """
SELECT paragraph.para_id
from 'data/paragraph.parquet'
inner join 'data/session.parquet' using(session_id)
where session.date between make_date(?, 1, 1) and make_date(?, 12, 31)
"""


@dc.dataclass
class SearchFilterSpec:

    start_year: int = 1901
    end_year: int = 3000
    text: str = ""

    def create_query(self) -> list[str, list[Any]]:
        """
        Create the SQL query to generate a table of matching paragraph ids.

        This prunes out filters that will have no effect, such as a blank text search.

        """

        queries = []
        params = []

        if self.text:
            queries.append(TEXT_QUERY)
            params.append(self.text)

        queries.append(DATE_QUERY)
        params.extend((self.start_year, self.end_year))

        # If there's only mandatory filters active...
        if len(queries) == 1:
            queries.append(
                "SELECT para_id from 'data/paragraph.parquet' using sample 100"
            )

        return "\nINTERSECT\n".join(queries), params

    def _repr_html_(self):
        return h("dl")(
            (h("dt")(key), h("dd")(val)) for key, val in dc.asdict(self).items()
        ).render()


@dc.dataclass
class SearchResults:

    rows: iterable

    def render_row(self, row):
        """Render a single row nice and compact."""
        return h("div")(
            h("div")(row[0]),
            h("div")(h("span")(h("em")(row[2])), " ", h("span")(row[1])),
        )

    def _repr_html_(self):
        """Render as HTML in the notebook."""

        return h("ol")(
            h("li")(self.render_row(row)) for row in self.rows.fetchall()
        ).render()


class UI:

    def __init__(self) -> None:

        button_layout = widgets.Layout(width="90%", height="2lh")
        wide_layout = widgets.Layout(width="90%")
        style = {"description_width": "25%"}

        self.search_text = widgets.Text(
            value="",
            placeholder="",
            description="Search text:",
            layout=wide_layout,
            style=style,
        )

        self.start_year = widgets.BoundedIntText(
            value=1996,
            min=1996,
            max=2026,
            step=1,
            description="Start year:",
            layout=wide_layout,
            style=style,
        )

        self.end_year = widgets.BoundedIntText(
            value=2026,
            min=1996,
            max=2026,
            step=1,
            description="End year:",
            layout=wide_layout,
            style=style,
        )

        self.run_button = widgets.Button(
            description="Search",
            layout=wide_layout,
        )
        self.run_button.on_click(self.run_search)

        self.display_transcripts = widgets.Output()

        self.conn = duckdb.connect()

        self.conn.execute("CREATE temporary table matching(para_id Int64)").fetchall()
        self.conn.execute("PRAGMA disable_progress_bar")

        # Container for the final output
        self.display_ui = widgets.VBox(
            [
                self.search_text,
                widgets.HBox(
                    [self.start_year, self.end_year], layout=widgets.Layout(width="90%")
                ),
                self.run_button,
                self.display_transcripts,
            ]
        )

        display(self.display_ui)

    def get_search_filters(self) -> SearchFilterSpec:
        """Get the current state of the search filters."""

        return SearchFilterSpec(
            text=self.search_text.value,
            start_year=self.start_year.value,
            end_year=self.end_year.value,
        )

    def set_search_filters(self, filters: SearchFilterSpec) -> None:
        """
        Reset to the provided search filters.

        This will be used to support history (eventually).

        """

        self.search_text.value = filters.text
        self.start_year.value = filters.start_year
        self.end_year.value = filters.end_year

    def matching_transcript_rows(self):
        """Retrieve the matching rows of the last run query."""
        return self.conn.execute("""
            SELECT
                session.date,
                -- This is necessary to avoid mathjax rendering in the jupyter cell...
                replace(paragraph.text, '$', '\\$') as text,
                speaker.display_name
            from 'data/paragraph.parquet'
            inner join matching using(para_id)
            inner join 'data/session.parquet' using(session_id)
            inner join 'data/speaker.parquet' on paragraph.speaker_id = speaker.phid
            order by session.date
            limit 1000
            """)

    def run_search(self, button: widgets.Button) -> None:
        """Run the search with the currently set filters."""

        try:
            self.display_transcripts.clear_output()

            # Implementation note: to avoid dynamically building a query that matches the
            # search spec, each separate filter generates a result set of matching row
            # identifiers, that can then be intersected together to get the final result.
            filters = self.get_search_filters()

            query, params = filters.create_query()

            self.conn.execute("DROP table matching")
            self.conn.execute("CREATE temporary table matching(para_id Int64)")

            with self.display_transcripts:
                self.conn.execute("INSERT into matching\n" + query, params)
                display(filters)
                display(SearchResults(self.matching_transcript_rows()))

        except Exception as e:
            with self.display_transcripts:
                print(
                    "Whoops, something went wrong - try again with different parameters"
                )
                print(e)
