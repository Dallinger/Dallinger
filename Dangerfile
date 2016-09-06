# Note contributors not in the organization.
unless github.api.organization_member?('Dallinger', github.pr_author)
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

warn("Please label as 'enhancement', 'bug', 'demo', or 'release'.", sticky: true) if !has_label

# Require change log entries on PRs with a release label.
fail("Please update the change log for this release.") if release && !git.modified_files.include?("CHANGELOG.md")
