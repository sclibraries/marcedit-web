# TASK-176 browser smoke evidence

- Image: `marcedit-web:task-176` from implementation commit `29a4b71`
- Opened URL: `http://127.0.0.1:18501/`
- Settled URL: `http://127.0.0.1:18501/?start=quick`
- Page title: `Smith College Libraries MARC21 workflow application`
- Text search: `/MarcEdit Web|MarcEditor/` returned no matches
- Screenshot: unavailable. Full-page, viewport, and element screenshot
  attempts each timed out at the connector's fixed five-second limit while
  waiting for the page/fonts to stabilize. This snapshot is durable evidence,
  but it is not a screenshot.

## Accessibility snapshot

```text
- generic [ref=f1e2]:
  - generic [ref=f1e7]:
    - list [ref=f1e10]:
      - generic [ref=f1e11]:
        - generic [ref=f1e12] [cursor=pointer]: Start
        - listitem [ref=f1e14]:
          - link "upload_file Home" [ref=f1e16] [cursor=pointer]:
            - /url: http://127.0.0.1:18501/
            - generic [ref=f1e17]: upload_file
            - generic [ref=f1e20]: Home
      - generic [ref=f1e21]:
        - generic [ref=f1e22] [cursor=pointer]: Inspect
        - listitem [ref=f1e24]:
          - link "visibility View" [ref=f1e26] [cursor=pointer]:
            - /url: http://127.0.0.1:18501/View
            - generic [ref=f1e27]: visibility
            - generic [ref=f1e30]: View
        - listitem [ref=f1e31]:
          - link "rule Validate" [ref=f1e33] [cursor=pointer]:
            - /url: http://127.0.0.1:18501/Validate
            - generic [ref=f1e34]: rule
            - generic [ref=f1e37]: Validate
        - listitem [ref=f1e38]:
          - link "insights Report" [ref=f1e40] [cursor=pointer]:
            - /url: http://127.0.0.1:18501/Report
            - generic [ref=f1e41]: insights
            - generic [ref=f1e44]: Report
      - generic [ref=f1e45]:
        - generic [ref=f1e46] [cursor=pointer]: Convert
        - listitem [ref=f1e48]:
          - link "swap_horiz Marc Tools" [ref=f1e50] [cursor=pointer]:
            - /url: http://127.0.0.1:18501/MarcTools
            - generic [ref=f1e51]: swap_horiz
            - generic [ref=f1e54]: Marc Tools
    - generic [ref=f1e58]:
      - heading "Smith College Libraries MARC21 workflow application" [level=2] [ref=f1e62]
      - paragraph [ref=f1e66]: v0.3.0
      - paragraph [ref=f1e70]:
        - text: Signed in as
        - strong [ref=f1e71]: anonymous
      - separator [ref=f1e75]
      - paragraph [ref=f1e79]: No file loaded yet.
  - generic [ref=f1e3]:
    - banner
    - generic [ref=f1e82]:
      - heading "Smith College Libraries MARC21 workflow application" [level=1] [ref=f1e87]
      - paragraph [ref=f1e92]: MARC21 viewer, validator, editor, and diff — in your browser.
      - heading "Upload a MARC file" [level=2] [ref=f1e97]
      - generic [ref=f1e100]:
        - paragraph [ref=f1e103]: Start path
        - radiogroup "Start path" [ref=f1e104] [cursor=pointer]:
          - generic [ref=f1e105]:
            - radio "Quick Load" [checked]
            - paragraph [ref=f1e110]: Quick Load
          - generic [ref=f1e111]:
            - radio "Job Workspace"
            - paragraph [ref=f1e116]: Job Workspace
      - heading "Quick Load" [level=3] [ref=f1e121]
      - paragraph [ref=f1e126]: Use this for one-off viewing, validation, reports, editing, or conversion.
      - generic [ref=f1e129]:
        - paragraph [ref=f1e132]: Choose a .mrc file
        - region "Choose a .mrc file" [ref=f1e139] [cursor=pointer]:
          - button "Choose File" [ref=f1e140]
          - generic [ref=f1e146]:
            - generic [ref=f1e147]: Drag and drop file here
            - generic [ref=f1e148]: Limit 2GB per file • MRC, MARC
          - button "Browse files" [ref=f1e150]
      - alert [ref=f1e153]:
        - paragraph [ref=f1e158]:
          - text: Upload a
          - code [ref=f1e159]: .mrc
          - text: file above to begin. Nothing persists across sessions — closing the tab discards everything.
```
