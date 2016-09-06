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
has_enhancement_label = github.pr_labels.include?("enhancement")
has_bug_label = github.pr_labels.include?("bug")
warn("Please label as 'enhancement', 'bug', 'demo', or 'release'.", sticky: true) if !has_enhancement_label && !has_bug_label
