# Third-party notices

The application distribution includes these direct dependencies installed
into the application Docker image. Their license texts and notices are
available from the linked upstream projects. Installed distributions retain
the license metadata supplied by upstream.

| Project | License | Upstream source |
| --- | --- | --- |
| [Streamlit](https://github.com/streamlit/streamlit) | Apache-2.0 | https://github.com/streamlit/streamlit |
| [pymarc](https://github.com/pymarc/pymarc) | BSD-2-Clause | https://github.com/pymarc/pymarc |
| [streamlit-ace](https://github.com/okld/streamlit-ace) | MIT | https://github.com/okld/streamlit-ace |
| [Authlib](https://github.com/authlib/authlib) | BSD-3-Clause | https://github.com/authlib/authlib |
| [pytest](https://github.com/pytest-dev/pytest) | MIT | https://github.com/pytest-dev/pytest |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | MIT | https://github.com/python-jsonschema/jsonschema |

These notices cover direct dependencies installed from `requirements.txt`.
Transitive dependencies retain the license metadata supplied in their
installed distributions.

## Compatibility corpora

The repository also preserves the partner-library `FOLIO Marc Edit Tasks`
collection from [jenmawe/marcedit](https://github.com/jenmawe/marcedit) at
commit `d07377a58cba9d0936a63863c9d428498609d5e5`. Those third-party task
archives remain licensed under GPL-3.0; their license and provenance notice
are retained in `third_party/task-corpora/jenmawe-marcedit/`. The root MIT
license does not relicense that corpus.
