echo "machine api.github.com\n  login DallingerBot\n  password $CHANDLER_GITHUB_API_TOKEN" > ~/.netrc
chmod 0600 ~/.netrc
chandler push
