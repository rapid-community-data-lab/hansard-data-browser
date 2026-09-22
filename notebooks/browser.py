# ---
# jupyter:
#   jupytext:
#     cell_metadata_filter: -all
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Proceedings of Australian Federal Parliament Analytical Browser
#
# This is a small search and export interface for the analytical dataset produced from
# the Proceedings of Australian Federal Parliament by the [RAPID-CDL project](https://rapid-cdl.edu.au). It is designed to let you quickly explore the proceedings
# by content, then export a specific extract for further analysis.
#
# Run this notebook by hitting the ▶▶ ("restart kernel and run all cells") button in the
# menu above - you'll be asked if you want to restart this notebook - answer 'yes' and
# the notebook will be run.
#
# Follow the prompts to set your search parameters, read and adjust your query based on
# the results, then hit `Export results` to generate a spreadsheet of the matching
# speeches. A progress bar will appear during processing and when complete a link to
# download the results will appear.
#
# ## Dataset Availability
#
# The underlying dataset is [archived on Zenodo](https://doi.org/10.5281/zenodo.22868754) and the software that compiles this dataset is [opensource and archived](https://doi.org/10.5281/zenodo.18946434). All of the underlying transcripts are released under the [CC-BY-ND-NC licence by the Australian Federal Parliament](https://www.aph.gov.au/Help/Disclaimer_Privacy_Copyright#c).
#
# ## Acknowledgment and Citation
#
# This dataset was prepared by the Reusable and Accessible Public Interest Documents project (RAPID-CDL). RAPID-CDL is a co-investment partnership with the Australian Research Data Commons (ARDC) through the HASS and Indigenous Research Data Commons (DOI: 10.3565/y37z-4y53). The ARDC is enabled by the Australian Government’s National Collaborative Research Infrastructure Strategy (NCRIS).
#
# You can cite this tool and the underlying dataset as follows:
#

# %%
from ui import UI

interface = UI()

# %% [markdown]
# # What the Search Filters Do
#
# ## Search Text
#
# The text search is a regular expression search over the text of the proceedings. The interpretation of the search text is controlled by the `Search for whole words` checkbox and the `Case sensitive` checkbox.
#
# If `Search for whole words` is checked (default), then the search string is broken up into individual words using whitespace, and only exact matching words are checked. For example if the search is `apple pear banana`, speeches containing `apple`, `pear`, or `banana` will match, but not variations like `apples` and `bananas`.
#
# If `Search for whole words` is turned off, the search text is treated as a regular expression using the [RE2 syntax](https://github.com/google/re2/wiki/Syntax). When not searching for whole words a query like `AI` will match both the word-unit `AI`, but also text inside words like `paint`. This can be used to create precise queries for certain forms, for example the syntax `.?` in `job.?ready graduates` will optionally match any character between `job` and `ready`. This will match `job-ready graduates`, `jobready graduates`, and `job ready graduates`.
#
# If `Case sensitive` is not checked (default), matches will be made regardless of the case of the text. A search for `Banana` will match `banana`, `BANANA`, and `Banana`.
#
# If `Case sensitive` is checked (default), matches will take into account the case of the text. A search for `AI` will match only `AI` and not `ai`.
#
# ## Parties
#
# The party the speaker belongs to, at the time of the speaking/producing the text. Parliamentarians can and do change parties.
#
# Note that not all text is linked to a specific speaker. This may be because:
#
# * the text indicates procedural details (e.g. "The SPEAKER took the chair at 09:00, made an acknowledgement of country and read prayers")
# * the attributed speaker of the text is acting in a role such as the Speaker of the House or the President of the Senate: we are currently working on improving our handling of this particular case.
# * there may be an issue with the speaker id in that particular section (for example an invalid speaker code). This is especially prominent in early transcripts where OCR errors make matching speakers difficult.
# * they may be a guest speaker (such as an address by a foreign leader) that is not formally part of parliament.
#
# ## House
#
# Limit the search to just the House of Representatives or the Senate.
#
# ## Start Year / End Year
#
# The start and end range of the years to search. Both ends are included in the range.
#

# %% [markdown]
# # What's in the Export?
#
# The search preview shows just the matching paragraphs/small units of text that match the search with a brief outline of the context. It's intended to be a dense reading view to show you the details of the specific search in context. The export takes those individual fine grained matches and places them in the context of the broader procedural units of the proceedings (most typically speeches).
#
# Currently the export includes the following columns:
#
# - *chamber*: The house of Parliament.
# - *date*: The sitting day.
# - *sitting_day_url*: A link to the transcript of that full sitting day.
# - *debate_title*: The title of the debate/procedural context in which the text was produced.
# - *procedural_unit_type*: The type of procedural unit (speech, petition, question, answer, motionnospeech)
# - *procedural_unit_number*: The sequence number of the procedural unit within the days transcript.
# - *speaker_name*: The name of the speaker.
# - *speaker_gender*: The gender of the speaker.
# - *speaker_party*: The party of the speaker (at the time of the speech).
# - *text_matches*: If search text was provided, the text that matched in that paragraph will be included here. This may be empty.
# - *text*: The text included in the proceedings (typically transcribed text, but may also indicate procedural or written text).

# %%
