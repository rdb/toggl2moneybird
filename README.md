# toggl2moneybird

A user-friendly command-line tool for synchronizing time entries from
[Toggl Track](https://toggl.com/track/) to [Moneybird](https://www.moneybird.com/).

<img width="426" alt="image" src="https://github.com/rdb/toggl2moneybird/assets/194842/12f05a72-c536-4c75-9aff-658439cc267d">

## Installation

    pip install toggl2moneybird

## Running

Using the tool is self-explanatory.  On first-time use, a browser window will
open asking you to authorize the tool to access your Moneybird administration.
It will also ask you for your Toggl Track email address and password as needed,
but you may alternatively enter the API token listed at the bottom of your
[profile page](https://track.toggl.com/profile).

To start the synchronization, type the following command.  The tool will always
ask you to confirm any changes, so you do not need to worry about the tool
automatically making changes to your administration.

    toggl2moneybird sync

You can also automatically create a draft invoice for a particular contact and
period using the following command:

    toggl2moneybird invoice

## Limitations

Currently, there is no mapping done between users - all time entries will be
logged under the same user (you will be asked which one if there are multiple).

It's not likely that you'll hit the rate limit of the Moneybird API using this
tool, but if you do, the tool does not handle it gracefully and will quit with
an exception.  Simply try again at a later time if you encounter this issue.

If you encounter any problems, please do not hesitate to report them in the
[issue tracker](https://github.com/rdb/toggl2moneybird/issues).
