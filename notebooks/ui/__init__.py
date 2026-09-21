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
import re

from tinyhtml import h, raw
import duckdb
import ipywidgets as widgets


@dc.dataclass
class SearchFilterSpec:

    start_year: int = 1901
    end_year: int = 3000
    text: str = ""
    tokenised: bool = True
    case_sensitive: bool = False
    parties: list[str] = dc.field(default_factory=list)
    houses: list[str] = dc.field(default_factory=list)

    def __post_init__(self):

        # If all is selected that's the only one that matters.
        if "All" in self.parties:
            self.parties = ("All",)

        if "All" in self.houses:
            self.houses = ("All",)

    def create_query(self) -> list[str, list[Any]]:
        """
        Create the SQL query to generate a table of matching paragraph ids.

        This prunes out filters that will have no effect, such as a blank text search.

        """

        joins = []
        clauses = []
        params = []
        needs_speaker = False

        base_query = """
            INSERT into matching
                SELECT
                    paragraph.para_id
                from 'data/paragraph.parquet'
                inner join 'data/session.parquet' using (session_id)
                {}
                where {}

        """

        if self.parties and "All" not in self.parties:
            needs_speaker = True
            clauses.append("speaker_detail.party in ?")
            params.append(self.parties)

        if self.houses and "All" not in self.houses:
            clauses.append("session.chamber in ?")
            params.append(self.houses)

        if needs_speaker:
            joins.append(
                "inner join 'data/speaker_detail.parquet' using(speaker_detail_id)"
            )

        clauses.append(
            "session.date between make_date(?, 1, 1) and make_date(?, 12, 31)"
        )
        params.extend((self.start_year, self.end_year))

        if self.text:

            options = "c" if self.case_sensitive else "i"

            if self.tokenised:
                search = "|".join(rf"\b{t}\b" for t in self.text.split())
            else:
                search = self.text

            clauses.append("regexp_matches(text, ?, ?)")

            params.extend((search, options))

        join = "\n".join(joins)
        where = " and\n".join(clauses)
        query = base_query.format(join, where)

        return query, params

    def highlight_regex(self):
        """
        Return a regular expression that can be used to highlight search matches.

        There may be some edges cases where the Python re module does not have the
        same beahviour as the re2 module used in duckdb...

        """
        options = re.NOFLAG if self.case_sensitive else re.IGNORECASE

        if self.tokenised:
            search = "|".join(rf"\b{t}\b" for t in self.text.split())
        else:
            search = self.text

        return re.compile(search, flags=options)

    def _repr_list(self, val):

        if isinstance(val, tuple):
            return h("ul")([h("li")(v) for v in val])
        else:
            return val

    def _repr_html_(self):
        return h("dl")(
            (h("dt")(key), h("dd")(self._repr_list(val)))
            for key, val in dc.asdict(self).items()
        ).render()


@dc.dataclass
class SearchResults:

    rows: iterable
    highlight_re: re.Pattern | None = None

    def _replace_match(self, match):

        return f"<mark>{match.group(0)}</mark>"

    def render_row(self, row):
        """Render a single row nice and compact."""
        text = row[6]

        if self.highlight_re is not None:
            text = raw(self.highlight_re.sub(self._replace_match, text))

        return h("div")(
            h("h3")(h("a", href=row[0])(row[1], ", ", row[2], ", ", row[3])),
            h("p")(h("span")(h("em")(row[5], ", ", row[4], ":")), " ", h("span")(text)),
        )

    def _repr_html_(self):
        """Render as HTML in the notebook."""

        return h("div")(self.render_row(row) for row in self.rows.fetchall()).render()


class UI:

    def __init__(self) -> None:

        # Initialise db
        self.conn = duckdb.connect()

        self.conn.execute("CREATE temporary table matching(para_id Int64)").fetchall()
        self.conn.execute("PRAGMA disable_progress_bar")
        self.current_offset = 0

        # setup all the UI elements.
        button_layout = widgets.Layout(width="90%", height="2lh")
        wide_layout = widgets.Layout(width="90%")
        selector_layout = widgets.Layout(width="95%")
        style = {"description_width": "25%"}

        self.search_text = widgets.Text(
            value="",
            placeholder="",
            description="Search text:",
            layout=wide_layout,
            style=style,
        )

        self.tokenised = widgets.Checkbox(
            value=True, description="Search for whole words"
        )
        self.case_sensitive = widgets.Checkbox(
            value=False, description="Case sensitive"
        )

        party_options = ["All"]
        party_options.extend(
            row[0]
            for row in self.conn.execute(
                "SELECT distinct party from 'data/speaker_detail.parquet'"
            ).fetchall()
        )
        self.parties = widgets.SelectMultiple(
            value=["All"],
            options=sorted(party_options),
            description="Parties",
            style=style,
            layout=selector_layout,
        )

        house_options = ["All"]
        house_options.extend(
            row[0]
            for row in self.conn.execute(
                "SELECT distinct chamber from 'data/session.parquet'"
            ).fetchall()
        )
        self.houses = widgets.SelectMultiple(
            value=["All"],
            options=sorted(house_options),
            description="House:",
            style=style,
            layout=selector_layout,
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

        self.next_page_button = widgets.Button(
            description="Next Page",
        )
        self.next_page_button.on_click(self.next_page)

        self.prev_page_button = widgets.Button(
            description="Prev Page",
        )
        self.prev_page_button.on_click(self.prev_page)

        self.pagination = widgets.HBox([self.prev_page_button, self.next_page_button])

        self.display_transcripts = widgets.Output()

        # Container for the final output
        self.display_ui = widgets.VBox(
            [
                self.search_text,
                widgets.HBox(
                    [self.tokenised, self.case_sensitive],
                    layout=widgets.Layout(width="90%"),
                ),
                widgets.HBox(
                    [self.parties, self.houses], layout=widgets.Layout(width="90%")
                ),
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
            parties=self.parties.value,
            houses=self.houses.value,
            tokenised=self.tokenised.value,
            case_sensitive=self.case_sensitive.value,
        )

    def set_search_filters(self, filters: SearchFilterSpec) -> None:
        """
        Reset to the provided search filters.

        This will be used to support history (eventually).

        """

        self.search_text.value = filters.text
        self.start_year.value = filters.start_year
        self.end_year.value = filters.end_year

    def matching_transcript_rows(self, n_results=50, offset=0):
        """Retrieve the matching rows of the last run query."""
        return self.conn.execute(
            """
            SELECT
                session.url,
                session.chamber,
                session.date,
                debate_title.title,
                speaker_detail.given_name,
                speaker_detail.family_name,
                -- This is necessary to avoid mathjax rendering in the jupyter cell...
                replace(paragraph.text, '$', '\\$') as text
            from 'data/paragraph.parquet'
            inner join matching using(para_id)
            inner join 'data/debate_title.parquet' using(debate_id)
            inner join 'data/session.parquet' on
                paragraph.session_id = session.session_id
            inner join 'data/speaker_detail.parquet' using(speaker_detail_id)
            order by session.date
            limit ?
            offset ?
            """,
            [n_results, offset],
        )

    def current_results_page(self):
        """Display the current page of results."""

        self.display_transcripts.clear_output()

        filters = self.get_search_filters()
        with self.display_transcripts:
            display(filters)
            display(self.pagination)
            display(
                SearchResults(
                    self.matching_transcript_rows(offset=self.current_offset),
                    highlight_re=filters.highlight_regex(),
                )
            )
            display(self.pagination)

    def next_page(self, button):
        self.current_offset += 50
        self.current_results_page()

    def prev_page(self, button):
        self.current_offset = max(0, self.current_offset - 50)
        self.current_results_page

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
                display(filters)
                self.conn.execute(query, params)
                self.current_offset = 0
                self.current_results_page()

        except Exception as e:
            with self.display_transcripts:
                display(e)
                print(
                    "Whoops, something went wrong - try again with different parameters"
                )
