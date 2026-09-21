"""TASK-253: a completed conversion must offer usable binary output."""

from streamlit.testing.v1 import AppTest


def test_binary_conversion_download_renders_without_exception():
    def app():
        from marcedit_web.lib import converters
        from marcedit_web.render.marc_tools import _offer_download_binary

        text = "=LDR  00000nam a2200000 a 4500\n=001  converted\n"
        result = converters.to_binary_from_mrk(text)
        _offer_download_binary(result.output, len(text))

    at = AppTest.from_function(app).run()
    assert not at.exception
    assert len(at.get("download_button")) == 1
    assert at.get("download_button")[0].proto.url
