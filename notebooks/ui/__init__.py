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

from pathlib import Path
from typing import Literal
import dataclasses as dc
import datetime as dt
import re
import time

from IPython.display import HTML
from openpyxl import Workbook, styles
from openpyxl.utils.cell import get_column_letter
from tinyhtml import h, raw
import duckdb
import ipywidgets as widgets


@dc.dataclass
class SearchFilterSpec:

    start_year: int = 1901
    end_year: int = 3000
    text: str = ""
    search_type: Literal["word-any", "word-all", "regex"] = "word-any"
    case_sensitive: bool = False
    parties: list[str] = dc.field(default_factory=list)
    houses: list[str] = dc.field(default_factory=list)
    matching_paragraphs: int = 0
    matching_speeches: int = 0

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

            search, options = self.get_search_regex()

            if isinstance(search, list):
                for s in search:
                    clauses.append("regexp_matches(text, ?, ?)")
                    params.extend((s, options))
            else:
                clauses.append("regexp_matches(text, ?, ?)")
                params.extend((search, options))

        join = "\n".join(joins)
        where = " and\n".join(clauses)
        query = base_query.format(join, where)

        return query, params

    def get_search_regex(self):
        """Get the regular expression to be used as the text search."""
        options = "c" if self.case_sensitive else "i"

        if self.search_type == "word-any":
            search = "|".join(rf"\b{t}\b" for t in self.text.split())

        elif self.search_type == "word-all":
            search = [rf"\b{t}\b" for t in self.text.split()]

        elif self.search_type == "regex":
            search = self.text
        else:
            raise ValueError(f"Unknown search type: {self.search_type}")

        return (search, options)

    def highlight_regex(self):
        """
        Return a regular expression that can be used to highlight search matches.

        There may be some edges cases where the Python re module does not have the
        same beahviour as the re2 module used in duckdb...

        """
        options = re.NOFLAG if self.case_sensitive else re.IGNORECASE

        # Highlighting should cover all words, even with searching for word-all (And)
        if self.search_type in ("word-any", "word-all"):
            search = "|".join(rf"\b{t}\b" for t in self.text.split())
        else:
            search = self.text

        return re.compile(search, flags=options)

    def pretty_print_key_values(self):
        """Pretty print the fields and values describing this search."""

        key_values = []

        key_values.append(("Years", f"{self.start_year}/{self.end_year}"))

        if self.text:
            search_description = {
                k: v
                for v, k in (
                    ("Match any word", "word-any"),
                    ("Match all words", "word-all"),
                    ("Match regular expression", "regex"),
                )
            }[self.search_type]
            key_values.append(("Search", self.text))
            key_values.append(("Case Sensitive", self.case_sensitive))
            key_values.append(("Search Type", search_description))

        if self.parties and "All" not in self.parties:
            key_values.append(("Parties", self.parties))

        if self.houses and "All" not in self.houses:
            key_values.append(("Chamber", self.houses))

        if self.matching_paragraphs:
            key_values.append(("Matching Paragraphs", self.matching_paragraphs))

        if self.matching_speeches:
            key_values.append(("Matching Speeches", self.matching_speeches))

        return key_values

    def _repr_html_(self):

        key_values = self.pretty_print_key_values()

        return h("dl")(
            (
                h("dt")(key),
                h("dd")(
                    h("ul")(h("li")(v) for v in value)
                    if isinstance(value, tuple)
                    else value
                ),
            )
            for key, value in key_values
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

        speaker_detail = None
        if row[5] or row[4]:
            speaker_detail = h("em")(row[5], ", ", row[4], ":")

        return h("div")(
            h("h3")(h("a", href=row[0])(row[1], ", ", row[2], ", ", row[3])),
            h("p")(h("span")(speaker_detail), " ", h("span")(text)),
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

        self.result_counts = (0, 0)

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

        self.search_type = widgets.Dropdown(
            value="word-any",
            options=[
                ("Match any word", "word-any"),
                ("Match all words", "word-all"),
                ("Match regular expression", "regex"),
            ],
            description="Search type:",
            layout=wide_layout,
            style=style,
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

        self.progress_bar = widgets.IntProgress(
            value=1,
            min=1,
            max=1,
            description="Export Progress:",
            bar_style="info",
            orientation="horizontal",
            style=style,
            layout=wide_layout,
        )

        self.run_button = widgets.Button(
            description="Search",
            layout=wide_layout,
        )
        self.run_button.on_click(self.run_search)

        self.export_button = widgets.Button(
            description="Export Results",
            layout=wide_layout,
        )
        self.export_button.on_click(self.export_search)

        self.next_page_button = widgets.Button(
            description="Next Page",
            layout=wide_layout,
        )
        self.next_page_button.on_click(self.next_page)

        self.prev_page_button = widgets.Button(
            description="Prev Page",
            layout=wide_layout,
        )
        self.prev_page_button.on_click(self.prev_page)

        self.pagination = widgets.HBox(
            [self.prev_page_button, self.next_page_button], layout=wide_layout
        )

        self.display_transcripts = widgets.Output(layout=wide_layout)

        self.space_widget = widgets.Output(layout=wide_layout)

        # Container for the final output
        self.display_ui = widgets.VBox(
            [
                widgets.HBox(
                    [self.search_text, self.search_type],
                    layout=wide_layout,
                ),
                widgets.HBox(
                    [self.space_widget, self.case_sensitive],
                    layout=wide_layout,
                ),
                widgets.HBox([self.parties, self.houses], layout=wide_layout),
                widgets.HBox([self.start_year, self.end_year], layout=wide_layout),
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
            search_type=self.search_type.value,
            case_sensitive=self.case_sensitive.value,
            matching_paragraphs=self.result_counts[0],
            matching_speeches=self.result_counts[1],
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
            -- left join because the speaker_id can be null or not mapped to anything.
            left outer join 'data/speaker_detail.parquet' using(speaker_detail_id)
            order by session.date, session.chamber, para_id
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
            display(h("h2")("Search Overview"))
            display(filters)
            display(self.export_button)
            display(self.pagination)
            display(h("h2")("Search Results"))
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

            self.result_counts = (0, 0)

            with self.display_transcripts:
                self.conn.execute(query, params)
                self.result_counts = self.conn.execute("""
                    SELECT
                        count(*),
                        count(distinct (session_id, procedural_unit_number))
                    from matching
                    inner join 'data/paragraph.parquet' using(para_id)
                    """).fetchall()[0]
                display(self.get_search_filters())
                self.current_offset = 0
                self.current_results_page()

        except Exception as e:
            with self.display_transcripts:
                display(e)
                print(
                    "Whoops, something went wrong - try again with different parameters"
                )

    def export_search(self, button: widgets.Button) -> None:
        """Export the current search results to a spreadsheet."""

        self.display_transcripts.clear_output()

        # TODO: progress bar
        # TODO: check the output size and make sure it fits in excel limits
        # TODO: provenance sheet indicating the query.

        with self.display_transcripts:
            try:

                filters = self.get_search_filters()
                display(h("h2")("Search Overview"))
                display(filters)

                regex_params = filters.get_search_regex()

                # Glue the match all words back into a regex to extract all instances.
                if isinstance(regex_params[0], list):
                    regex_params = ("|".join(regex_params[0]), regex_params[1])

                # Calculate the total rows for the export progress
                total_rows = self.conn.execute("""
                    WITH matching_units as (
                        SELECT distinct
                            session_id,
                            paragraph.procedural_unit_number
                        from 'data/paragraph.parquet'
                        inner join matching using(para_id)
                    )
                    select count(*)
                    from 'data/paragraph.parquet'
                    inner join matching_units using(session_id, procedural_unit_number)
                    """).fetchall()[0][0]

                self.progress_bar.value = 1
                self.progress_bar.max = total_rows * 3

                display(h("h2")("Exporting"))
                display(self.progress_bar)

                content_query = self.conn.execute(
                    """
                    WITH matching_units as (
                        SELECT distinct
                            session_id,
                            paragraph.procedural_unit_number
                        from 'data/paragraph.parquet'
                        inner join matching using(para_id)
                    )
                    SELECT
                        session.chamber,
                        session.date,
                        session.url,
                        debate_title.title,
                        paragraph.procedural_unit_type,
                        paragraph.procedural_unit_number,
                        speaker_detail.family_name || ', ' || speaker_detail.given_name,
                        speaker_detail.gender,
                        speaker_detail.party,
                        list_aggregate(
                            regexp_extract_all(
                                paragraph.text,
                                ?,
                                0,
                                ?
                            ),
                            'string_agg',
                            ', '
                        ) as matches,
                        paragraph.text
                    from 'data/paragraph.parquet'
                    inner join matching_units using(session_id, procedural_unit_number)
                    inner join 'data/debate_title.parquet' using(debate_id)
                    inner join 'data/session.parquet' on
                        paragraph.session_id = session.session_id
                    -- left join because the speaker_id can be null or not mapped to anything.
                    left outer join 'data/speaker_detail.parquet' using(speaker_detail_id)
                    order by session.date, session.chamber, para_id
                    """,
                    regex_params,
                )

                workbook = Workbook()

                workbook.create_sheet("proceedings")

                workbook.create_sheet("provenance")
                worksheet = workbook["provenance"]

                worksheet.append(["Field", "Value"])

                field_values = filters.pretty_print_key_values()

                # Very basic provenance information.
                field_values.extend(
                    (
                        ("dateCreated", dt.datetime.now()),
                        ("wasGeneratedBy", "https://doi.org/10.5281/zenodo.22887645"),
                        ("derivedFrom", "https://doi.org/10.5281/zenodo.22868754"),
                        (
                            "hadPrimarySource",
                            "https://parlinfo.aph.gov.au/parlInfo/search/search.w3p",
                        ),
                    )
                )

                for field, value in field_values:
                    v = value
                    if isinstance(value, tuple):
                        v = ", ".join(value)
                    worksheet.append((field, v))

                workbook.remove(workbook["Sheet"])

                worksheet = workbook["proceedings"]

                header = [
                    "chamber",
                    "date",
                    "sitting_day_url",
                    "debate_title",
                    "procedural_unit_type",
                    "procedural_unit_number",
                    "speaker_name",
                    "speaker_gender",
                    "speaker_party",
                    "text_matches",
                    "text",
                ]

                worksheet.append(header)

                last_update = time.monotonic()
                written_rows = 0
                while row := content_query.fetchone():
                    worksheet.append(row)
                    written_rows += 1

                    if time.monotonic() - last_update > 0.2:
                        self.progress_bar.value += written_rows
                        written_rows = 0
                        last_update = time.monotonic()

                self.progress_bar.value += written_rows

                # Update transcript link to be a proper hyperlink
                all_rows = worksheet.rows
                next(all_rows)  # skip header

                for row in all_rows:
                    link = row[2].value

                    row[2].hyperlink = link
                    row[2].value = "Sitting Day Transcript"

                    written_rows += 1

                    if time.monotonic() - last_update > 0.2:
                        self.progress_bar.value += written_rows
                        written_rows = 0
                        last_update = time.monotonic()

                self.progress_bar.value += written_rows

                # Zebra stripe speeches and set text to wrap
                all_rows = worksheet.rows
                next(all_rows)  # skip header

                colour = True
                last_speech = (None, None, None)

                solid_fill = styles.PatternFill(fill_type="solid", fgColor="efefef")

                for row in all_rows:

                    current_speech = (row[0].value, row[1].value, row[5].value)

                    if current_speech != last_speech:
                        colour = not colour
                        last_speech = current_speech

                    if colour:
                        for cell in row:
                            cell.fill = solid_fill

                    for cell in row:
                        cell.alignment = styles.Alignment(
                            wrap_text=True, vertical="top", horizontal="left"
                        )

                    written_rows += 1

                    if time.monotonic() - last_update > 0.2:
                        self.progress_bar.value += written_rows
                        written_rows = 0
                        last_update = time.monotonic()

                self.progress_bar.value += written_rows

                # Format column widths and alignments for readability
                for i, header in enumerate(header):
                    col = worksheet.column_dimensions[get_column_letter(i + 1)]

                    col.width = 15

                    if header == "text":
                        col.width = 50

                # Freeze the header
                worksheet.freeze_panes = "A2"

                output_folder = Path("outputs")
                output_folder.mkdir(exist_ok=True)
                output = output_folder / "exported_speeches_AU_Federal_Parliament.xlsx"

                workbook.save(output)

                display(
                    HTML(
                        f'<a href="{output}" download>Download your search results.</a>'
                    )
                )

            except Exception as e:
                display(e)
                print("something went wrong")
