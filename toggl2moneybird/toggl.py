__all__ = 'TogglTrack',

import requests
from base64 import b64encode

from rich.pretty import pprint


class APIError(Exception):
    def __init__(self, code):
        self.code = code


class TogglTrack:
    def __init__(self, data):
        self.__data = data

        encoded = b64encode(data['api_token'].encode('ascii') + b':api_token')
        self.__headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic ' + encoded.decode('ascii'),
        }
        self.__projects = None
        self.__workspaces = {}

    @property
    def fullname(self):
        return self.__data['fullname']

    @property
    def api_token(self):
        return self.__data['api_token']

    def _request(self, method, path, data=None):
        url = f'https://api.track.toggl.com/api/v9/{path}'

        r = requests.request(method, url, headers=self.__headers, json=data)
        if r.status_code >= 300:
            print(f"{method} {url}")
            pprint(r)
            try:
                pprint(r.json())
            except Exception:
                print(r.text)
            raise APIError(r.status_code)

        return r.json()

    def get_workspace(self, id):
        if id is None:
            return None

        if id in self.__workspaces:
            return self.__workspaces[id]

        workspace = self._request('GET', f'workspaces/{id}')
        self.__workspaces[id] = workspace
        return workspace

    def __fetch_projects(self):
        self.__projects = {}
        for project in self._request('GET', 'me/projects?include_archived=true'):
            self.__projects[project['id']] = project

    def get_project(self, id):
        if id is None:
            return None

        if self.__projects is None:
            self.__fetch_projects()
            assert self.__projects is not None

        return self.__projects.get(id)

    def get_projects(self):
        if self.__projects is None:
            self.__fetch_projects()
            assert self.__projects is not None

        return list(self.__projects.values())

    def get_time_entries(self, start_date=None, end_date=None):
        path = 'me/time_entries'
        if start_date and end_date:
            path += f'?start_date={start_date:%Y-%m-%d}&end_date={end_date:%Y-%m-%d}T23:59:59Z'

        return self._request('GET', path)

    @staticmethod
    def login(email, password="api_token"):
        r = requests.get('https://api.track.toggl.com/api/v9/me', headers={
            'Content-Type': 'application/json',
            'Authorization': 'Basic ' + b64encode(f'{email}:{password}'.encode('utf-8')).decode('ascii'),
        })
        if r.status_code == 200:
            return TogglTrack(r.json())
        else:
            return None
