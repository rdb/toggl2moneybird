__all__ = ()

from datetime import datetime

from . import moneybird as mb


def tt_parse_timestamp(str):
    return datetime.fromisoformat(str.replace('Z', '+00:00'))


class SyncEntry:
    def __init__(self, start, tt_project, billable, description):
        self.billable = billable
        self.tt_project = tt_project
        self.description = description
        self.start = start
        self.paused_duration = 0
        self.mb_project = None
        self.mb_entry = None


class EntrySync:
    def __init__(self):
        self.entries = []
        self.__entry_map = {}
        self.__project_map: dict[int, mb.Project] = {}
        self.__missing_projects: dict[int, dict] = {}
        self.__mb_project_contact_map: dict[mb.Project, mb.Contact] = {}

    def add_tt_entry(self, tt_entry, tt_project):
        # Must be called in chronological order.

        tt_project_id = tt_entry['project_id']
        if tt_project_id:
            assert tt_project['id'] == tt_project_id
        else:
            assert not tt_project

        billable = tt_entry['billable']
        description = tt_entry['description']

        date = tt_entry['start'][0:10]
        start = tt_parse_timestamp(tt_entry['start'])

        key = (date, tt_entry['billable'], tt_project_id, tt_entry['description'])
        entry = self.__entry_map.get(key)
        if entry:
            # Merge equivalent entries for this day
            entry.paused_duration += int((start - entry.stop).total_seconds())
        else:
            entry = SyncEntry(start, tt_project, billable, description)
            self.__entry_map[key] = entry
            self.entries.append(entry)

            if tt_project:
                entry.mb_project = self.__project_map.get(tt_project_id)
                if not entry.mb_project:
                    self.__missing_projects[tt_project_id] = tt_project

        entry.stop = tt_parse_timestamp(tt_entry['stop'])

    def link(self, mb_entries):
        """Links up the SyncEntries with the given list of Moneybird entries.
        Returns a new list of unused Moneybird entries."""

        # Create mappings from project -> contact and timestamp -> entry.
        mb_existing_entries_by_time = {}
        mb_redundant_entries = mb.TimeEntries()
        for mb_entry in mb_entries:
            self.__mb_project_contact_map[mb_entry.project] = mb_entry.contact

            key = mb_entry.started_at.isoformat()[:16]
            if key not in mb_existing_entries_by_time:
                mb_existing_entries_by_time[key] = mb_entry
            else:
                # It's an apparent duplicate.
                mb_redundant_entries.append(mb_entry)

        # Assign based on existing entries in moneybird.
        for entry in self.entries:
            key = entry.start.isoformat()[:16]
            mb_entry = mb_existing_entries_by_time.get(key)
            if not mb_entry:
                continue

            entry.mb_entry = mb_entry

            mb_project = mb_entry.project
            entry.mb_project = mb_project

            mb_contact = mb_entry.contact

            tt_project = entry.tt_project
            if mb_project:
                if tt_project and tt_project['id'] not in self.__project_map:
                    self.__project_map[tt_project['id']] = entry.mb_project
                    self.__missing_projects.pop(tt_project['id'], None)

                if mb_contact:
                    self.__mb_project_contact_map[mb_project] = mb_contact

            del mb_existing_entries_by_time[key]

        # Update project for entries that have none.
        for entry in self.entries:
            if not entry.mb_project:
                tt_project = entry.tt_project
                entry.mb_project = tt_project and self.__project_map.get(tt_project['id'])

        # Leftover entries are redundant.
        for mb_entry in mb_existing_entries_by_time.values():
            mb_redundant_entries.append(mb_entry)

        return mb_redundant_entries

    def get_project_by_tt_id(self, tt_project_id):
        return self.__project_map.get(tt_project_id)

    def map_project(self, tt_project_id, mb_project):
        assert tt_project_id
        assert mb_project
        self.__project_map[tt_project_id] = mb_project
        self.__missing_projects.pop(tt_project_id, None)

        for entry in self.entries:
            if entry.tt_project and entry.tt_project['id'] == tt_project_id:
                entry.mb_project = mb_project

    def has_missing_billable_projects(self):
        for proj in self.__missing_projects.values():
            if proj['billable']:
                return True
        return False

    def map_projects_by_name(self, mb_projects):
        if not self.entries or not self.__missing_projects:
            return

        # Make a reverse mapping from moneybird project name to ID.
        mb_projects_by_name = {}
        for mb_project in mb_projects:
            mb_projects_by_name[mb_project.name.lower()] = mb_project

        for entry in self.entries:
            tt_project = entry.tt_project
            if tt_project:
                tt_project_id = tt_project['id']
                project_name = tt_project['name'].lower()
                mb_project = mb_projects_by_name.get(project_name)
                if mb_project:
                    entry.mb_project = mb_project
                    self.__project_map[tt_project_id] = mb_project
                    self.__missing_projects.pop(tt_project_id, None)

        return tuple(self.__missing_projects.values())

    def set_project_contact(self, mb_project, mb_contact):
        assert mb_project
        assert mb_contact
        self.__mb_project_contact_map[mb_project] = mb_contact

    def get_project_contact(self, mb_project):
        return self.__mb_project_contact_map.get(mb_project)

    def get_billable_projects_without_contacts(self):
        for mb_project in self.__project_map.values():
            if mb_project not in self.__mb_project_contact_map:
                for entry in self.entries:
                    if entry.mb_project == mb_project and entry.billable:
                        yield mb_project
                        break

    def get_new_updated_entries(self, mb_user):
        mutations = []

        for entry in self.entries:
            mb_project = entry.mb_project
            if not mb_project:
                continue

            mb_contact = self.get_project_contact(mb_project)
            if not mb_contact:
                continue

            data = {
                'user_id': str(mb_user.id),
                'contact_id': str(mb_contact.id),
                'project_id': str(mb_project.id),
                'billable': entry.billable,
                'description': entry.description,
                'started_at': entry.start.isoformat()[:16] + ':00.000Z',
                'ended_at': entry.stop.isoformat()[:16] + ':00.000Z',
                'paused_duration': entry.paused_duration,
            }

            if entry.mb_entry:
                diff = entry.mb_entry.get_data_diff(data)
                if diff:
                    mutations.append((entry.mb_entry, diff))
            else:
                mutations.append((None, data))

        return mutations
