"""Resolve the newest RSNA/RadLex version tag and fetch the ontology it publishes.

Usage: python3 site/resolve_input.py --out DIR [--repo OWNER/NAME]

Prints one JSON object: tag, commit, tag_date, source, path, sha256. The newest tag is
the highest tag matching TAG_PATTERN, compared numerically. The input is the first that
exists of: an .owl or .owl.zip asset on the tag's GitHub release, RadLex.owl at the tag
commit, and a .ofn edit file at the tag commit.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

TAG_PATTERN = re.compile(r"^v?\d+(\.\d+)+$")
DEFAULT_REPO = "RSNA/RadLex"


class ResolveError(Exception):
    pass


def version_key(tag):
    return tuple(int(part) for part in tag.lstrip("v").split("."))


def version_tags(ls_remote_text):
    """(tag, commit) for every version tag in `git ls-remote --tags` output, newest first.

    An annotated tag lists its tag object and then its peeled commit under `^{}`, and
    the peeled commit wins.
    """
    commits = {}
    for line in ls_remote_text.splitlines():
        if not line.strip():
            continue
        sha, ref = line.split()
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/"):]
        peeled = name.endswith("^{}")
        name = name.removesuffix("^{}")
        if not TAG_PATTERN.match(name):
            continue
        if peeled or name not in commits:
            commits[name] = sha
    return sorted(commits.items(), key=lambda pair: version_key(pair[0]), reverse=True)


def select_tag(ls_remote_text):
    """(tag, commit) for the newest version tag."""
    tags = version_tags(ls_remote_text)
    if not tags:
        raise ResolveError("no tag matches " + TAG_PATTERN.pattern)
    return tags[0]


def ls_remote(repo):
    return run(["git", "ls-remote", "--tags", f"https://github.com/{repo}.git"])


def run(cmd, cwd=None, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def github_api(path):
    """GET a GitHub API path, with GITHUB_TOKEN when set. Returns None on 404."""
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def release_assets(repo, tag):
    """The tag's release assets as (name, download URL) pairs, or [] with no release."""
    release = github_api(f"repos/{repo}/releases/tags/{tag}")
    if not release:
        return []
    return [(a["name"], a["browser_download_url"]) for a in release.get("assets", [])]


def pick_asset(assets):
    """The first .owl asset, else the first .owl.zip asset, else None."""
    for suffix in (".owl", ".owl.zip"):
        for name, url in assets:
            if name.lower().endswith(suffix):
                return name, url
    return None


def download(url, dest):
    with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)


def unzip_owl(zip_path, out_dir):
    """Extract the zip's .owl member, preferring RadLex.owl, else the largest."""
    with zipfile.ZipFile(zip_path) as zf:
        owls = [i for i in zf.infolist() if i.filename.lower().endswith(".owl") and not i.is_dir()]
        if not owls:
            raise ResolveError(f"{zip_path.name} holds no .owl file")
        named = [i for i in owls if Path(i.filename).name == "RadLex.owl"]
        member = named[0] if named else max(owls, key=lambda i: i.file_size)
        dest = out_dir / Path(member.filename).name
        with zf.open(member) as src, open(dest, "wb") as fh:
            while chunk := src.read(1 << 20):
                fh.write(chunk)
    return dest


class TagCheckout:
    """A blobless, depth-1 clone of one tag: trees only, blobs fetched on demand."""

    def __init__(self, repo, tag, workdir):
        self.dir = Path(workdir) / "repo"
        run(["git", "clone", "--quiet", "--depth", "1", "--branch", tag, "--filter=blob:none",
             "--no-checkout", f"https://github.com/{repo}.git", str(self.dir)])

    def commit_date(self):
        return run(["git", "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%d", "HEAD"],
                   cwd=self.dir, env={**os.environ, "TZ": "UTC"}).strip()

    def paths(self):
        return run(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=self.dir).splitlines()

    def export(self, path, dest):
        with open(dest, "wb") as fh:
            subprocess.run(["git", "show", f"HEAD:{path}"], cwd=self.dir, check=True, stdout=fh)


def pick_repo_file(paths):
    """RadLex.owl at the root, else a .ofn file (an *-edit.ofn first), as (source, path)."""
    if "RadLex.owl" in paths:
        return "repo-owl", "RadLex.owl"
    ofn = sorted(p for p in paths if p.endswith(".ofn"))
    edit = [p for p in ofn if p.endswith("-edit.ofn")]
    if edit or ofn:
        return "repo-ofn", (edit or ofn)[0]
    return None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(repo, out_dir, pick=None):
    """Fetch the input of `pick`, a (tag, commit) pair, or of the newest tag."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag, commit = pick or select_tag(ls_remote(repo))
    with tempfile.TemporaryDirectory() as work:
        checkout = TagCheckout(repo, tag, work)
        tag_date = checkout.commit_date()
        asset = pick_asset(release_assets(repo, tag))
        if asset:
            name, url = asset
            source = "release-asset"
            if name.lower().endswith(".zip"):
                zip_path = Path(work) / name
                download(url, zip_path)
                path = unzip_owl(zip_path, out_dir)
            else:
                path = out_dir / name
                download(url, path)
        else:
            picked = pick_repo_file(checkout.paths())
            if not picked:
                raise ResolveError(f"tag {tag} has no OWL release asset, RadLex.owl, or .ofn file")
            source, repo_path = picked
            path = out_dir / Path(repo_path).name
            checkout.export(repo_path, path)
    return {"tag": tag, "commit": commit, "tag_date": tag_date, "source": source,
            "path": str(path), "sha256": sha256_file(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="directory to write the input file into")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub OWNER/NAME to read tags from")
    args = parser.parse_args(argv)
    try:
        record = resolve(args.repo, args.out)
    except ResolveError as err:
        sys.exit(f"resolve_input: {err}")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
