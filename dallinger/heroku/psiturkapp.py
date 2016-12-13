"""Launch the experiment server."""

from dallinger.experiment_server import app

def run_webserver():
    ''' Run web server '''
    host = "0.0.0.0"
    port = 5000
    app.run(debug=True, host=host, port=port)

if __name__ == '__main__':
    run_webserver()

