#!/usr/bin/env bash
#
# Helper script for creating a release in either UAT or production.
#
# This script is meant to be called by the `release` target in the Makefile due
# to the environment already being set up in the make file.
#
# The flow is as follows:
#
# * $ make release
# * This script is called
# * If not on either `main` or `UAT` branch, error exit
# * If any uncommitted changes, error exit
# * If on UAT:
#    * Always RC releases
#    * If not RC already (just merged in from main):
#        * Ask if major or minor should be bumped?
#        * Always zero patch
#        * Zero minor if major is bumped
#        * Set _rc0
#    * Increase rc level
#    * Write to VERSION
#    * Commit change
#    * Add tag
#    * Commit
#    * Push change and tags
#    * If no MR, create one
# * On main:
#    * If not on RC version:
#       * If not a bugfix, remind to merge UAT
#       * Else allow bumping the patch version
#    * Else, drop RC
#    * Write to VERSION
#    * Commit change
#    * Add tag
#    * Commit
#    * Push change and tags
#
# Overrides:
# ----------
# It's possible to test the functionality by settings some overrides. These
# are:
#
# * SKIP_BR=1    - Skip the check for UAT or main branch. Assume UAT unless on main
# * FORCE_MAIN=1 - Always assume main even on UAT. Also helpful with SKIP_BR=1
# * SKIP_UNTRACK=1 - Ignore any untracked files in the repo
# * SKIP_DIRTY=1 - Ignore any tracked changes or uncommited staged files
# * VERSION=x.y.z_rcN - can override the current version number for testing
#
# Example:
#     make release SKIP_BR=1 SKIP_UNTRACK=1 VERSION=1.2.3_rc2 SKIP_DIRTY=1 FORCE_MAIN=1
#

# We exit if any command exit with non-zero

### --------Constants--------
ME=$(basename $0)

# Check to see if glab is available.
if $(which glab >/dev/null 2>&1); then
    HAS_GLAB=true
else
    HAS_GLAB=false
fi

# The current branch we're on.
BRANCH=$(git branch --show-current)

# Figure out current repo state
# Check for unstaged changes (modified but not staged for commit)
GIT_UNSTAGED=$(git diff --quiet || echo true)
# Check for staged but uncommitted changes
GIT_UNCOMMITTED=$(git diff --cached --quiet || echo true)
# Check for untracked files
GIT_UNTRACKED=$(test -n "$(git ls-files --others --exclude-standard)" && echo true)
# Check for unpushed commits (only if remote exists)
if git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
    GIT_UNPUSHED=$(test -n "$(git log --branches --not --remotes)" && echo true)
fi
# Default false if not set
GIT_UNSTAGED=${GIT_UNSTAGED:-false}
GIT_UNCOMMITTED=${GIT_UNCOMMITTED:-false}
GIT_UNTRACKED=${GIT_UNTRACKED:-false}
GIT_UNPUSHED=${GIT_UNPUSHED:-false}
# echo "GIT_UNSTAGED=$GIT_UNSTAGED"
# echo "GIT_UNCOMMITTED=$GIT_UNCOMMITTED"
# echo "GIT_UNTRACKED=$GIT_UNTRACKED"
# echo "GIT_UNPUSHED=$GIT_UNPUSHED"

# The source file we get the current version from
VERSION_SOURCE=version.py

# Set VERSION from the VERSION_SOURCE
VERSION=$(python -c "from ${VERSION_SOURCE%.py} import VERSION; print(VERSION)")


# These will be set by parseVersion from the global VERSION env var
V_BASE=
V_MAJOR=
V_MINOR=
V_PATCH=
V_RC=

### --------Functions--------
###
# Exits with an error message passed in as the fist argument
###
function errorExit () {
    echo -e "\nERROR:\n  $*\n"
    exit 1
}

###
# Displays a question and accepts only yes/no input replies.
#
# Args:
#   $1 : The prompt to display
#
# Returns:
#  0 for Yes or 1 for No
###
function YesNo () {
    prompt="$1 (y/n): "
    ans=

    while [[ $ans != 'y' && $ans != 'n' ]]; do
        read -p "$prompt" -N 1 ans
        echo ""
        case $ans in
            "y" | "Y" ) return 0 ;;
            "n" | "N" ) return 1 ;;
        esac
        echo "Invalid response. Please answer with y or n only."
    done
}

###
# Parses the VERSION environment variable set by the Makefile into these parts:
# V_BASE - the base after stripping and rc part
# V_MAJOR
# V_MINOR
# V_PATCH
# V_RC
###
function parseVersion () {
    # First validate the VERSION format
    if ! echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(_rc[0-9]+)?$'; then
        errorExit "Invalid VERSION format: $VERSION"
    fi

    # First split the base from any RC component
    case "$VERSION" in
        *_rc*)
            V_BASE=${VERSION%%_rc*}
            V_RC=${VERSION##*_rc}
            ;;
        *)
            V_BASE=$VERSION
            V_RC=""
            ;;
    esac

    # This trick splits V_BASE into $1, $2 and $3 on IFS which we set to a
    # period but only in the local context
    local IFS='.'
    set -- $V_BASE
    V_MAJOR=$1
    V_MINOR=$2
    V_PATCH=$3
}

###
# This called from UATRelease or mainRelease after the V_MAJOR, V_MINOR,
# V_PATCH and V_RC values have been updated to the new release values.
#
# This function updates VERSION, adds the tag and pushes the changes and tags
###
function setRelease () {
    # This is the new version. If this is an RC version, we will add _rcN,
    # otherwise it is the production type version.
    NEW_VER=${V_MAJOR}.${V_MINOR}.${V_PATCH}${V_RC:+_rc}${V_RC}

    # Update the VERSION file
    sed -i "s/^VERSION = .*/VERSION = \"$NEW_VER\"/" $VERSION_SOURCE || \
        errorExit "Error writing new version to $VERSION_SOURCE file"

    # Stage and commit the change
    git add $VERSION_SOURCE || errorExit "Error staging the $VERSION_SOURCE file"
    git commit -m "Set version: v${NEW_VER}" || errorExit "Error commit version change"

    # Add the tag
    git tag -m "Release: v${NEW_VER}" "v${NEW_VER}" || errorExit "Error adding tag"

    if ! YesNo "New version has been set and tag created. Do you want to push this?"; then
        echo "Not pushing. This change can still be rolled back."
        echo "Aborting..."
        exit 1
    fi

    git push && git push --tags
}

###
# Handle RC releases on UAT.
#
# This function just updates the version components after possibly bumping the
# major or minor versions.
#
# It also confirms the new version for release
###
function UATRelease () {
    # First thing we do is check if there are any changes on main that still
    # needs to be merged into UAT. This will normally be needed after a
    # production deployment. We use git log to see any commits that have been
    # made on main, but not merged into UAT yet. We can not just use 
    # git diff UAT main because it will falsy trigger an any changes that may
    # have been made on UAT too, and we're only interested in changes on main.
    echo "Checking for changes in 'main'..."
    # Fetch latest info about 'main' from remote if available
    git fetch origin main >/dev/null 2>&1
    # Fetch all commits onto main that was not in UAT
    MAIN_CHANGES=$(git log --oneline origin/main --not UAT)
    if [[ -n $MAIN_CHANGES ]]; then
        echo "⚠ The following commits on 'main' have not been merged into 'UAT' yet:"
        echo "$MAIN_CHANGES"
        echo -e "\nPlease merge 'main' into 'UAT' before continuing.\n"
        exit 1
    fi

    echo -e "\nCreating a release candidate version in UAT, from current version: $VERSION."

    # If there is no RC, then this must a fresh merge from main. We need to
    # know which part to bump.
    if [[ -z $V_RC ]]; then
        echo "No release candidate set yet, so assuming this is after a merge from main."
        while true; do
            echo ""
            prompt="Current version is ${VERSION} - Bump which part, [m]ajor, mi[n]or or [q]uit (m/n/q)? "
            read -p "$prompt" -N 1 part
            echo ""
            case "$part" in
                "m" | "M" )
                    V_MAJOR=$(($V_MAJOR + 1))
                    V_MINOR=0
                    V_PATCH=0
                    V_RC=0
                    break
                    ;;
                "n" | "N" )
                    V_MAJOR=$V_MAJOR
                    V_MINOR=$(($V_MINOR + 1))
                    V_PATCH=0
                    V_RC=0
                    break
                    ;;
                "q" | "Q" )
                    echo "Aborting..."
                    exit 0
                    ;;
                * )
                    echo "Invalid reply. Please try again."
                    continue
                    ;;
            esac
        done
    fi

    # Now we can increase the RC part.
    V_RC=$(($V_RC + 1))

    if ! YesNo "Going from version $VERSION to ${V_MAJOR}.${V_MINOR}.${V_PATCH}_rc${V_RC} - continue?"; then
        echo "Aborting setting release version..."
        exit 1
    fi
}

###
# Handles a bugfix release.
#
# Bugfixes are done from main if the current version is not an RC version.
#
# We bump the patch version and ask for confirmation, or allow aborting the
# release.
###
function bugfixRelease () {

    # Bump the patch
    V_PATCH=$((V_PATCH + 1))

    prompt="Create production bugfix release ${V_MAJOR}.${V_MINOR}.${V_PATCH}?"
    if ! YesNo "$prompt"; then
        echo "Aborting setting bugfix release version..."
        exit 1
    fi
}

###
# Handle releases on main
#
# If not an RC release, try for a bugfix and return if bugfix patch has been
# set.
#
# Else for an RC release, drop the RC part because we assume RCs have passed
# and we do a proper version release now.
#
# It confirms the release version and updates the version parts if needed, and
# lastly confirms that this is the release we will go to now.
###
function mainRelease () {
    # If we are not on an RC version, this may be a bugfix ralease
    if [[ -z $V_RC ]]; then
        echo -e "\nCurrent version is $VERSION - not a Release Candidate.\n"

        if ! YesNo "Is this a bugfix release?"; then
            echo -e "\nIt looks like you need to merged from UAT to get the"\
                    "latest RC release ready\n" \
                    "Can not release from this version, aborting...\n"
            exit 1
        fi
        
        # Try the bugfix
        bugfixRelease

        # If we did not exit already, the patch version has been set, so we can
        # return to set the version
        return
    fi

    # Reset RC part.
    V_RC=

    prompt="Create production release version ${V_MAJOR}.${V_MINOR}.${V_PATCH} from current version $VERSION?"

    if ! YesNo "$prompt"; then
        echo "Aborting setting release version..."
        exit 1
    fi
}

###
# Checks if glab is available and if so checks to see if we need to create an
# MR, and creates one if the user accepts.
###
function checkMR () {
    OK="\033[0;32m✔\033[0m"
    NOK="\033[0;31m✖\033[0m"

    # The MR functionality is only for the UAT branch
    if [[ $BRANCH != 'UAT' ]]; then
        return
    fi

    # We need to have glab cli available
    if [[ $HAS_GLAB = 'false' && $SKIP_GLAB -ne 1 ]]; then
        echo -e "\nTo auto manage MRs, try installing 'glab', the GitLab cli."
        echo -e "See: https://gitlab.com/gitlab-org/cli\n"
        exit 0
    fi

    # Check if there is already an MR for the release using the glab cli The
    # output from the mr list command looks something like this (not exact):
    #
    #   !13  gaulnet/battery-capacity-meter-ui!13    Release Candidate  (main) ← (UAT)
    #
    # The !N at the start is the MR number. The "Release Candidate" is the
    # title we assign when creating the MR, and then we also have the
    # target and source branches. All these are used to find the correct
    # MR.
    HAS_MR=$(glab mr list --source-branch=UAT --target-branch=main 2>/dev/null | \
             grep -E '^![0-9]+.*Release.*main.*UAT' | wc -l)
    if [[ $HAS_MR -eq 1 ]]; then
        echo -e "\n${OK} An MR to merge UAT into main already exists.\n"
        exit 0
    fi

    if ! YesNo "Would you like to create an MR to merge this release into main?"; then
        echo -e "\nOK, maybe next time.\n"
        exit 0
    fi

    # Create the MR
    glab mr create -t "Release ${V_MAJOR}.${V_MINOR}.${V_PATCH}" \
        -d "Merge UAT into main for release" \
        -s UAT --squash-before-merge -b main
}

###
# Main runtime function
###
function main () {
    # If MAKELEVEL is not set, we have probably not been called from make release
    [[ -z $MAKELEVEL ]] && errorExit "Please run as 'make release' and not directly."

    # We must be on either main or UAT branches or SKIP_BR must be 1
    if [[ $BRANCH != 'UAT' && $BRANCH != 'main' && $SKIP_BR -ne 1 ]]; then
        errorExit "Releases can only be done from the UAT or main branches. This branch is: $BRANCH"
    fi

    # We need a clean repo - except if we force SKIP_DIRTY=1
    if [[ ($GIT_UNSTAGED = 'true' || $GIT_UNCOMMITTED = 'true') && $SKIP_DIRTY -ne 1 ]]; then
        errorExit "There are unstaged or uncommitted changes. Please stash or commit and try again."
    fi

    # Any untracked files
    if [[ $GIT_UNTRACKED = 'true' && $SKIP_UNTRACK -ne 1 ]]; then
        errorExit "There are untracked files in the repo. To ignore, set call with SKIP_UNTRACK=1."
    fi

    # Parse VERSION into it's components
    parseVersion

    # Update the release version
    if [[ $BRANCH = "main" || $FORCE_MAIN -eq 1 ]]; then
        mainRelease
    else
        # Also going here when not on UAT but SKIP_BR=1
        UATRelease
    fi

    # Write the new release version, set the tag and push the repo.
    setRelease

    # Check if we need to create and MR
    checkMR
}


main

