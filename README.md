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

Only time entries corresponding to a project are synced.  By default, only
billable items are synced, but you can add the `--include-unbillable` flag to
include unbillable items as well.

You can also automatically create a draft invoice for a particular contact and
period using the following command:

    toggl2moneybird invoice

The invoice will not be sent out automatically.  Instead, a browser window will
open with the draft invoice in Moneybird, allowing you to send it from there.

## Billable flag

By default, only entries marked "Billable" in Toggl Track are synchronized.
There are two options to control this behaviour.  The `--include-unbillable`
flag will cause all entries to be synchronized.  The "Billable" flag is only
set in moneybird for entries that are marked "Billable" in Toggl Track.

Since the "Billable" tag requires a paid Toggl Track subscription, there is an
option to use a custom tag instead.  If you use `--unbillable-tag "My Tag"`,
then all Toggl Track entries will be considered billable, except those with
the tag "My Tag".  The option may be repeated for every tag that marks an
unbillable entry.  If you would like to mark all imported entries billable in
moneybird, simply use this option with a silly tag name that doesn't exist.

The options are independent of each other and may be used together, in which
case *all* entries (except those specified by `--exclude-tag`) are imported,
but only the ones without the tags specified by `--unbillable-tag` are marked
as "Billable" in the moneybird administration.

## Advanced Filters

You can use `--project` with most commands to limit the effect of those
commands to only the specified projects.

You can use `--exclude-tag "My Tag"` to entirely ignore Toggl Track entries
with the specified tag.

## Limitations

The Toggl Track API only allows accessing the last three months worth of data.
It is highly advised to run the sync at least once every month!

Currently, there is no mapping done between users - all time entries will be
logged under the same user (you will be asked which one if there are multiple).

It's not likely that you'll hit the rate limit of the Moneybird API using this
tool, but if you do, the tool does not handle it gracefully and will quit with
an exception.  Simply try again at a later time if you encounter this issue.

If you encounter any problems, please do not hesitate to report them in the
[issue tracker](https://github.com/rdb/toggl2moneybird/issues).
Feature requests are also welcome!
