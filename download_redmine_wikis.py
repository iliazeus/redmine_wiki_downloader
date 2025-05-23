#!/usr/bin/env python3

import argparse
import getpass
import json
import os
import re
import requests
import sys
import tomllib


with open("config.toml", "rb") as f:
    config = tomllib.load(f)

url = config["redmine"]["url"]
print("Redmine URL:", url)

user = config["redmine"].get("user") or getpass.getuser()
print("Redmine user:", user)

password = config["redmine"].get("password") or getpass.getpass("Redmine password: ")

base_dir = os.getcwd()


def get_data_from_endpoint(target_url):
    response = requests.get(target_url, auth=(user, password))
    try:
        response_object = json.loads(response.content)
    except json.decoder.JSONDecodeError:
        print(f"There was an issue with: {target_url}")
        response_object = {'wiki_page': ''}
    return response_object


def gather_projects():
    all_projects = {}
    project_pass = {}
    offset = 0
    # TODO: check for project_pass['projects'] == []
    while offset < 100:
        target_url = url + f"projects.json?limit=100&offset={offset}"
        project_pass = get_data_from_endpoint(target_url)
        all_projects.update(project_pass)
        offset += 100
    return all_projects['projects']


def gather_wikis_from_project(identifier):
    target_url = url + "projects/" + identifier + "/wiki/index.json"
    try:
        return get_data_from_endpoint(target_url)['wiki_pages']
    except KeyError:
        return []


def get_wiki_page_and_attachments(identifier, wiki_title):
    target_url = url + "projects/" + identifier + "/wiki/" + wiki_title + ".json?include=attachments"
    return get_data_from_endpoint(target_url)['wiki_page']


def download_attachment(attachment_obj):
    target_url = attachment_obj['content_url']
    # replace spaces with underscores to prevent issues in markdown links
    filename = attachment_obj['filename'].replace(" ", "_")
    # response is a binary object of the file contents
    response = requests.get(target_url, auth = (user, password))
    # https://docs.python-requests.org/en/master/user/quickstart/#raw-response-content
    with open(filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size = 128):
            f.write(chunk)
    # Metadata for files is kept in the wiki metadata


def replace_redmine_wiki_with_textile_link(page_content):
    """
    Restructure links from [[Wiki Page]] to "Wiki page":wiki_page.md
    """
    proper = re.sub(pattern = r'\[\[(.*)\]\]', # capture text within [[]] tags
                    # must use a lambda to allow replacing within a group
                    # https://stackoverflow.com/a/56393435/7418735
                    repl = (lambda match :
                            # link text
                            '"' + match.expand(r"\1") + '"' +
                            # link path
                            ':' + match.expand(r"\1").replace(" ", "_") + ".md"
                            ),
                    string = page_content)
    return proper


def download_wiki_page(wiki_obj):
    wiki_title = wiki_obj['title']
    print()
    print("---")
    print(f"Downloading {wiki_title}")
    sys.stdout.flush()
    # page_content = replace_redmine_wiki_with_textile_link(wiki_obj.pop('text'))
    page_content = wiki_obj.pop('text')
    attachments = wiki_obj['attachments']
    if attachments:
        # append an unordered list of links to each attachment
        # use literal carraige returns to appease python, textile, and/or pandoc
        page_content += """\r\n\r\n"""
        page_content += "h2. Attachments:"
        for attachment in attachments:
            download_attachment(attachment)
            # append a Textile style link to the page
            # convert spaces to underscores in both link text and path
            filename = attachment['filename'].replace(" ", "_")
            attachment_link = f"\"{filename}\":<{filename}>"
            page_content += """\r\n"""
            page_content += f"""* {attachment_link}"""
    with open(wiki_title + ".textile", 'w') as f:
        f.write(page_content)
    # FIXME: convert textile to md now instead of needing a bash script
    # subprocess.run(["pandoc", f"{wiki_title}.textile -o {wiki_title}.md"])
    # subprocess.call(["rm", f"{wiki_title}.textile"])
    with open(wiki_title + "-metadata.json", 'w') as f:
        f.write(json.dumps(wiki_obj))


def download_project(identifier):
    print()
    print("===")
    print(f"Downloading project: {identifier}")
    project_wikis = gather_wikis_from_project(identifier)
    if project_wikis == []:
        print(f"{identifier} has no wiki, skipping")
        return
    project_dir = base_dir + "/" + identifier + "/"
    try:
        os.mkdir(project_dir)
    except FileExistsError:
        # dir exists already, just switch to it
        pass
    os.chdir(project_dir)
    project_wiki_map = {}
    # create a mapping to hierchically store in parent's dir
    for wiki in project_wikis:
        title = wiki['title']
        project_wiki_map.update({title: ''})
        if 'parent' in wiki:
            project_wiki_map[title] = wiki['parent']['title']

    for wiki in project_wikis:
        title = wiki['title']
        parent_title = title
        wiki_path = ""
        # prepend parents in file path to enforce nested hierarchy
        while project_wiki_map[parent_title] != '':
            parent_title = project_wiki_map[parent_title]
            wiki_path = parent_title + "/" + wiki_path

        wiki_path = project_dir + "/" + wiki_path
        wiki_obj = get_wiki_page_and_attachments(identifier, title)
        try:
            os.makedirs(wiki_path)
        except FileExistsError:
            # dir exists already, just switch to it
            pass
        os.chdir(wiki_path)
        if wiki_obj:
            download_wiki_page(wiki_obj)
    os.chdir(base_dir)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", help="Directory in which the wikis will be downloaded")
    args = parser.parse_args()
    if (args.output_dir):
        globals().update(base_dir = os.path.abspath(args.output_dir))
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
    projects = gather_projects()
    for project in projects:
        download_project(project['identifier'])
