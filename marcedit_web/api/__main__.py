"""Run the independent API on loopback with its configured URL prefix."""

from waitress import serve

from . import create_app


app = create_app()
serve(
    app,
    host="127.0.0.1",
    port=app.config["API_PORT"],
    url_prefix=app.config["API_URL_PREFIX"],
)
