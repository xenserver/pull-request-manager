# Pull Request Manager

## Description

A program that continually checks and potentially merges
[GitHub pull requests](http://help.github.com/pull-requests/).

## Protocol

The protocol used to choose a pull request to process is the following:

1. Find all open pull requests associated with the specified repositories;
2. From those, select only pull requests made by the administrators of these
   repositories;
3. For each pull request:
   * read its comments, and determine whether the bot's last attempt has
     `succeeded`, and whether either the repository's branch to which the pull
     request was made, or the pull request itself, has `changed` since the
     last attempt;
   * if an administrator of the repository has posted a comment that starts
     with _"Approved."_ (case ignored, dot required), and the bot has
     previously `succeeded` or the refs `changed`, prefer processing this pull
     request;
   * otherwise, process a pull request only if no pull request satisfies the
     previous step, and the corresponding refs of the pull request have
     `changed`.

Once a pull request has been chosen, it is processed as follows:

1. Try building the underlying system with the changesets from the pull
   request:

        make <component-for-pull-request's-repository>-build
        make api-build

   If these steps fail, report the problem as a comment on the pull request,
   and stop processing this pull request.

   While currently not enabled, it is easy to configure the bot to only
   re-build the system if refs have not `changed`. This is disabled, since it
   is safer to re-build the system before a merge even if the refs have not
   `changed`, because the bot is not checking refs of all dependent
   repositories (many of which are not on GitHub).

2. If a merge is requested (through administrator's _"Approved."_; see above),
   verify that refs have not `changed` since the pull request started being
   processed:
   * if refs have `changed`, report the problem as a comment on the pull
     request, and stop processing this pull request;
   * otherwise, push the changesets of the pull request into the requested
     branch of the main repository, comment about this on the pull request, and
     close the pull request.

The above process is repeated continuously. After every processed pull request,
or if there is no pull request to process, the program waits for a while
(1min). If a connection error occurs, the program waits for a longer period of
time (10min) before retrying.

## Dependencies

The program currently depends on:

* [python-github2](https://github.com/xen-org/python-github2), a Python
implementation of [GitHub's API](http://develop.github.com/).

## Setup

The following steps are required to run the program:

* Make sure the dependencies are satisfied;

* Create `private.py`, and within define `bot_email` and `bot_api_token`
variables with appropriate values; and,

* Create a `github-xen-git` target in your `.ssh/config` file, which points to
the bot's private key:

          Host github-xen-git
            HostName github.com
            User git
            IdentityFile /home/roks/.ssh/id_rsa_xen_git

## Running

To start the program, execute the following command:

    python main.py

## Feedback and Contributions

Feedback and contributions are welcome. Please submit contributions
via GitHub pull requests.
