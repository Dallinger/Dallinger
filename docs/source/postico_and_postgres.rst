Viewing the PostgreSQL Database
===============================

Postico is a nice tool for examining Postgres databases on OS X. We use
it to connect to live experiment databases. Here are the steps needed to
do this:

1. Download `Postico <https://eggerapps.at/postico/>`__ and place it in
   your Applications folder.
2. Open Postico.
3. Press the "New Favorite" button in the bottom left corner to access a
   new database.
4. Get the database credentials from the Heroku dashboard:

   -  Go to https://dashboard.heroku.com/apps/{app\_id}/resources
   -  Under the **Add-ons** subheading, go to "Heroku Postgres ::
      Database"
   -  Note the database credentials under the subheading "Connection
      Settings". You'll use these in step 5.

5. Fill in the database settings in Postico. You'll need to include the:

   -  Host
   -  Port
   -  User
   -  Password
   -  Database

6. Connect to the database.

   -  You may see a dialog box pop up saying that Postico cannot verify
      the identity of the server. Click "Connect" to proceed.
