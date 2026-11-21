"""Open/update one issue per failed binary target; close it after a good build."""

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import quote
from urllib.request import Request, urlopen

from ci_binary import targets


def request(method: str, path: str, body: dict | None = None):
    repo = os.environ['GITHUB_REPOSITORY']
    token = os.environ['GH_TOKEN']
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f'https://api.github.com/repos/{repo}{path}', data=data, method=method,
                  headers={
                      'Accept': 'application/vnd.github+json',
                      'Authorization': f'Bearer {token}',
                      'X-GitHub-Api-Version': '2022-11-28',
                      'Content-Type': 'application/json',
                  })
    with urlopen(req, timeout=20) as response:
        return json.load(response) if response.status != 204 else None


def matching_issue(title: str):
    for page in range(1, 11):
        issues = request('GET', f'/issues?state=open&per_page=100&page={page}')
        for issue in issues:
            if 'pull_request' not in issue and issue['title'] == title:
                return issue
        if len(issues) < 100:
            break
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('failed', 'passed'))
    parser.add_argument('target', choices=tuple(targets()))
    args = parser.parse_args()
    title = f'[binary:{args.target}] Build or load test failed'
    existing = matching_issue(title)
    if args.action == 'passed':
        if existing:
            request('POST', f'/issues/{existing["number"]}/comments', {
                'body': f'Validated binary available again in {run_url()}.'})
            request('PATCH', f'/issues/{existing["number"]}', {'state': 'closed'})
        return
    message = (
        f'Target: `{args.target}`\n\n'
        f'Workflow run: {run_url()}\n\n'
        f'Commit: `{os.environ.get("GITHUB_SHA", "unknown")}`\n\n'
        'The artifact for this target was not published. Other targets continue independently. '
        'See the failed job step for the compiler or load error.\n')
    if existing:
        request('POST', f'/issues/{existing["number"]}/comments', {'body': message})
        print(f'Updated issue #{existing["number"]}')
    else:
        issue = request('POST', '/issues', {'title': title, 'body': message})
        print(f'Created issue #{issue["number"]}')


def run_url() -> str:
    return (f'{os.environ.get("GITHUB_SERVER_URL", "https://github.com")}/'
            f'{quote(os.environ["GITHUB_REPOSITORY"])}/actions/runs/'
            f'{os.environ["GITHUB_RUN_ID"]}')


if __name__ == '__main__':
    main()
