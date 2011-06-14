import re, os, time, traceback
from github2.client import Github

# switch, which determines whether any real actions are executed
active = True

# set basic variables
bot_name = "xen-git"
import settings # bot_email, bot_api_token, builds_path
org_name = "xen-org"
rep_names = { # repository names to corresponding component names
    'filesystem-summarise' : 'filesystem-summarise',
    'stunnel' : 'stunnel',
    'xen-api': 'api',
    'xen-api-libs': 'api-libs',
    }
build_dir = "build-%s.hg" % bot_name
log_file = "build-%s.log" % bot_name
log_path = "%s/%s" % (settings.builds_path, log_file)
build_path = "%s/%s" % (settings.builds_path, build_dir)
build_rep = "http://hg/carbon/trunk/build.hg"
short_sleep = 60 # seconds
long_sleep = 600 # seconds

# result caches
branch_sha_cache = {}

# create an authenticating GitHub client
github = Github(username=bot_name,
                api_token=settings.bot_api_token,
                requests_per_second=1)

# determine admin usernames
teams = github.organizations.teams(org_name)
admin_team_ids = [t.id for t in teams if t.permission in ["admin", "push"]]
admins = sum([github.teams.members(id) for id in admin_team_ids], [])
admin_usernames = [admin.login for admin in admins]

# determine valid pull request authors
pr_team_ids = [t.id for t in teams if t.name == "Authorised pull request authors"]
pr_users = sum([github.teams.members(id) for id in pr_team_ids], [])
pr_usernames = [pr_user.login for pr_user in pr_users]
pr_usernames.extend(admin_usernames)

def get_next_pull_request():
    """Performs a fresh search, and obtains the next pull request to process,
    whether a re-build is required for this pull request, and whether the pull
    request should be merged."""
    backup_pr = None
    # for each repository
    for rep_name in rep_names:
        # get repository path
        rep_path = "%s/%s" % (org_name, rep_name)
        # fetch all open pull requests for this repository
        all_prs = github.pull_requests.list(rep_path, "open")
        # select only pull requests by trusted users
        valid_prs = [pr for pr in all_prs
                     if pr.user["login"] in pr_usernames]
        # if a pull request contains a specific comment, chose it immediately
        # otherwise, choose a pull request with no comments from bot or whose
        # refs have changed
        for valid_pr in valid_prs:
            comments = github.issues.comments(rep_path, valid_pr.number)
            succeeded, changed = should_rebuild(valid_pr, comments)
            # process if an admin approved it, and its last attempt to build it
            # was successful or refs have changed
            if is_approved(comments) and (succeeded or changed):
                log("APPROVED: %s/%d" % (rep_name, valid_pr.number))
                return valid_pr, True, True # rebuild, merge
            # otherwise, check if it should be processed anyway
            if changed: backup_pr = valid_pr
    return backup_pr, True, False # rebuild, don't merge

def is_approved(comments):
    """Checks whether any comment of a pull request starts with "@xen-git",
    followed by a regular expression specified on a line in "positive.txt"
    (case ignored), followed by '.' or '!', followed by any text."""
    ls = [l.strip() for l in open("positive.txt").readlines() if l.strip()]
    positive = "(%s)[.!]" % '|'.join(["(%s)" % l for l in ls])
    positive = "@%s %s" % (bot_name, positive)
    return [] != filter(lambda x: x,
                        [re.match(positive, c.body, re.I | re.U)
                         for c in comments if c.user in admin_usernames])

def should_rebuild(pr, comments):
    """Checks the pull requests and its comments to see whether the pull request
    has succeeded the last time, and whether the refs have changed."""
    rep_name = pr.base["repository"]["name"]
    # approve if no existing bot comments
    bot_comments = [c for c in comments if c.user == bot_name]
    if not bot_comments:
        log("NO COMMENTS: %s/%d" % (rep_name, pr.number))
        return False, True # "last build not succeeded", "refs changed"
    # otherwise, parse last bot's comment, and check for ref changes
    last_bot_comment = bot_comments[-1]
    first_line = last_bot_comment.body.split("\n")[0]
    succeeded = first_line.find("### Build succeeded.") == 0
    refs = re.findall("\S+?@\w+", first_line, re.U)
    last_pr_ref = refs[0]
    last_branch_ref = refs[1]
    current_pr_ref = get_pr_ref(pr)
    branch = pr.base["ref"]
    current_branch_ref = get_branch_ref(rep_name, branch)
    changed = last_pr_ref != current_pr_ref or last_branch_ref != current_branch_ref
    if changed: log("REFS CHANGED: %s/%d" % (rep_name, pr.number))
    return succeeded, changed

def report_error(pr, ex_msg, show_log):
    """Report an error regarding the given pull request with the given
    message. The message is reported on standard output and GitHub."""
    rep_name = pr.base["repository"]["name"]
    rep_path = "%s/%s" % (org_name, rep_name)
    pr_ref = get_pr_ref(pr)
    branch = pr.base["ref"]
    branch_ref = get_branch_ref(rep_name, branch)
    msg = "### Failed to merge and build %s with %s.\n%s" % (pr_ref, branch_ref, ex_msg)
    if show_log:
        msg += "\nError log:"
        f = open(log_path)
        lines = f.readlines()
        f.close()
        linesToPrint = min(20, len(lines))
        firstLineToPrint = len(lines) - linesToPrint
        for i in range(firstLineToPrint, firstLineToPrint + linesToPrint):
            msg += "\n    %s" % lines[i].rstrip()
    print_msg(pr, msg)
    if active: github.issues.comment(rep_path, pr.number, msg)

def print_msg(pr, msg):
    """Print the given message together with a unique identifier of the given
    pull request to standard output."""
    print "============================="
    print "Pull request: %s\n%s" % (pr.html_url, msg)
    print "============================="

def execute(path, cmd):
    """Execute the given command in the given path."""
    cwd = os.getcwd()
    os.chdir(path)
    log("Executing '%s' in '%s' ..." % (cmd, path))
    retcode = os.system("GIT_USER=%s %s 2>&1 >> %s" % (bot_name, cmd, log_path))
    os.chdir(cwd)
    return retcode

class BuildError(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return self.message

def execute_and_report(path, cmd):
    """Execute the given command in the given path, raising an exception for a
    non-zero return code."""
    if execute(path, cmd) != 0:
        raise BuildError("Failed when executing:\n    %s" % cmd)

class MergeError(Exception):
    def __init__(self, message):
        self.message = message
    def __str__(self):
        return self.message

def process_pull_request(pr, rebuild_required, merge):
    """If a rebuild is required, try building the system with the changesets
    from the given pull request. If the build succeeds and the merge has been
    requested, merge the pull request with the main repository. Perform the
    merge without building the system if a rebuild is not required."""
    if not rebuild_required and not merge:
        log("Invalid call: rebuild_required=False, merge=False")
        return
    rep_name = pr.base["repository"]["name"]
    rep_path = "%s/%s" % (org_name, rep_name)
    user = pr.user["login"]
    log("Processing pull request %s/%d .." % (rep_path, pr.number))
    component_name = rep_names[rep_name]
    rep_dir = "%s/myrepos/%s" % (build_path, rep_name)
    branch = pr.base["ref"]
    branch_sha = get_branch_sha(rep_name, branch)
    log("branch_sha: %s" % branch_sha)
    path_cmds = [
        (settings.builds_path, "sudo rm -rf %s %s" % (build_dir, log_file)),
        (settings.builds_path, "hg clone %s %s" % (build_rep, build_dir)),
        (build_path, "make manifest-latest"),
        ]
    for path, cmd in path_cmds: execute_and_report(path, cmd)
    for c in rep_names.itervalues(): execute_and_report(build_path, "make %s-myclone" % c)
    path_cmds = [
        (rep_dir, "git config user.name %s" % bot_name),
        (rep_dir, "git config user.email %s" % settings.bot_email),
        (rep_dir, "git checkout %s" % branch),
        (rep_dir, "git remote add {0} git://github.com/{0}/{1}.git".format(user, rep_name)),
        (rep_dir, "git fetch %s" % user),
        (rep_dir, "git merge %s" % pr.head["sha"]),
        ]
    for path, cmd in path_cmds: execute_and_report(path, cmd)
    if rebuild_required:
        execute_and_report(build_path, "make %s-build" % component_name)
        if component_name != "api":
            execute_and_report(build_path, "make api-build")
    pr_ref = get_pr_ref(pr)
    branch_ref = get_branch_ref(rep_name, branch)
    if merge:
        fresh_branch_sha = github.repos.branches(rep_path)[branch]
        if fresh_branch_sha != branch_sha:
            fresh_branch_ref = get_branch_ref(rep_name, branch, fresh_branch_sha)
            raise MergeError("Branch %s updated since to %s." % (branch, fresh_branch_ref))
        fresh_pr = github.pull_requests.show(rep_path, pr.number)
        if fresh_pr.state != "open":
            raise MergeError("Pull request %s no longer 'open'." % rep_path)
        if fresh_pr.head["sha"] != pr.head["sha"]:
            fresh_pr_ref = get_pr_ref(fresh_pr)
            raise MergeError("Pull request %s modified since to %s." % (rep_path, fresh_pr_ref))
        rep_url = "git@github-xen-git:%s.git" % rep_path
        path_cmds = [
            (rep_dir, "git remote add xen-org %s" % rep_url),
            (rep_dir, "git push xen-org %s" % branch),
            ]
        if active:
            for path, cmd in path_cmds: execute_and_report(path, cmd)
        msg = "### Build succeeded. Merged %s with %s." % (pr_ref, branch_ref)
        print_msg(pr, msg)
        if active:
            github.issues.comment(rep_path, pr.number, msg)
            github.issues.close(rep_path, pr.number)
    else:
        msg = "### Build succeeded. Can merge %s with %s." % (pr_ref, branch_ref)
        print_msg(pr, msg)
        if active: github.issues.comment(rep_path, pr.number, msg)

def get_branch_sha(rep_name, branch):
    """Obtain SHA of the last commit of the specified branch of the specified
    repository. The results are cached."""
    global branch_sha_cache
    rep_path = "%s/%s" % (org_name, rep_name)
    try:
        branch_sha = branch_sha_cache[(rep_path, branch)]
    except KeyError:
        branch_sha = github.repos.branches(rep_path)[branch]
        branch_sha_cache[(rep_path, branch)] = branch_sha
    return branch_sha

def get_branch_ref(rep_name, branch, branch_sha=None):
    if not branch_sha: branch_sha = get_branch_sha(rep_name, branch)
    return "%s/%s@%s" % (org_name, rep_name, branch_sha)

def get_pr_ref(pr):
    return "%s/%s@%s" % (pr.user["login"],
                         pr.base["repository"]["name"],
                         pr.head["sha"])

def clear_state():
    """Clears any global state due to the processing of pull requests."""
    global branch_sha_cache
    branch_sha_cache = {}

def log(msg):
    print "[%s] %s" % (time.ctime(), msg)

if __name__ == "__main__":
    """Continually obtain pull requests, and process them. If there are no pull
    requests to process, wait for a while."""
    while True:
        try:
            clear_state()
            log("Searching for pull request to process..")
            pr, rebuild_required, merge = get_next_pull_request()
            if pr:
                process_pull_request(pr, rebuild_required, merge)
            else:
                log("No appropriate pull requests found.")
            log("Sleeping for %ds." % short_sleep)
            time.sleep(short_sleep)
        except BuildError as ex:
            report_error(pr, ex.message, True)
        except MergeError as ex:
            report_error(pr, ex.message, False)
        except:
            traceback.print_exc()
            log("Unexpected error occurred. Sleeping for %ds." % long_sleep)
            time.sleep(long_sleep)
