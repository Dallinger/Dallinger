# Note contributors not in the organization.
is_member = github.api.organization_member?('Dallinger', github.pr_author)
is_bot = (github.pr_author == "pyup-bot")
unless is_member || is_bot
  message("@#{github.pr_author}, would you like to join the Dallinger org.?")
end

# Encourage writing up some reasoning about the PR.
if github.pr_body.length < 5
  fail("Please provide a summary in the Pull Request description.")
end

# Ensure a clean commit history.
if git.commits.any? { |c| c.message =~ /^Merge branch/ }
  fail('Please rebase to get rid of the merge commits.')
end

# Require labels on PRs.
enhancement = github.pr_labels.include?("enhancement")
bug = github.pr_labels.include?("bug")
release = github.pr_labels.include?("release")
demo = github.pr_labels.include?("demo")

has_label = enhancement || bug || release || demo

if !has_label
    warn("Please apply a label.")
end


# Require change log entries on PRs with a release label.
if release && !git.modified_files.include?("CHANGELOG.md")
    fail("Please update the change log for this release.")
end
