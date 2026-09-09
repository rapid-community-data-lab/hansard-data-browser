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

import duckdb
import ipywidgets as widgets

# There's one simple query per filter, always returning a set of identifiers to be
# intersected
TEXT_QUERY = """
SELECT para_id
from 'data/paragraph.parquet'
where ? in lower(text)
"""


@dc.dataclass
class SearchFilterSpec:
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

        # If there's no active queries choose randomly.
        if not queries:
            queries.append(
                "SELECT para_id from 'data/paragraph.parquet' using sample 100"
            )

        return "\nINTERSECT\n".join(queries), params


class UI:

    def __init__(self) -> None:

        button_layout = widgets.Layout(width="90%", height="2lh")
        wide_layout = widgets.Layout(width="90%")
        style = {"description_width": "40%"}

        self.search_bar = widgets.Text(
            value="",
            placeholder="",
            description="Search text:",
            disabled=False,
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

        # Container for the final output
        self.display_ui = widgets.VBox(
            [self.search_bar, self.run_button, self.display_transcripts]
        )

        display(self.display_ui)

    def get_search_filters(self) -> SearchFilterSpec:
        """Get the current state of the search filters."""

        return SearchFilterSpec(text=self.search_bar.value)

    def set_search_filters(self, filters: SearchFilterSpec) -> None:
        """
        Reset to the provided search filters.

        This will be used to support history (eventually).

        """

        self.search_bar = filters.text

    def display_transcripts(self) -> None:
        """Display the currently active set of transcripts."""

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
            self.conn.execute(
                "CREATE temporary table matching(para_id Int64)"
            ).fetchall()

            with self.display_transcripts:
                self.conn.execute("INSERT into matching\n" + query, params)
                print(self.conn.sql("SELECT * from matching").show())

        except Exception:
            self.display_transcripts.clear_output()
            with self.display_transcripts:
                print(
                    "Whoops, something went wrong - try again with different parameters"
                )
