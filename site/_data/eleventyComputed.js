/**
 * `linkBase`: the relative path from this page back to the site root.
 *
 * Every internal link is relative rather than absolute, so ONE build works in both places it has
 * to: served under /archive/ by the Fly worker, and opened straight off the shared drive as a
 * file:// URL with no server at all. An absolute /archive/... link breaks the offline copy (it
 * resolves to the filesystem root), and a bare /... link breaks the hosted one.
 *
 * Depth comes from page.url, which is the permalink Eleventy actually emitted:
 *   /                          -> ./        (0 segments)
 *   /browse/                   -> ../       (1)
 *   /item/<slug>/              -> ../../    (2)
 *   /outlet/external/page/2/   -> ../../../../ (4)
 *
 * The hosted side needs one thing for this to hold: /archive must redirect to /archive/. Without
 * the trailing slash a browser treats "archive" as a file and resolves "item/x/" against its
 * parent, landing on /item/x/. worker/app.py issues that redirect.
 */
module.exports = {
  linkBase: (data) => {
    const url = (data.page && data.page.url) || "/";
    const parts = url.split("/").filter(Boolean);
    // Drop a trailing FILE segment before counting: depth is how many directories deep the page
    // sits, and "/404.html" sits at the root while looking one level down.
    //
    // Every other page uses a directory permalink ("/topic/x/" -> topic/x/index.html), so the
    // naive count was right until 404.njk arrived with permalink "404.html". That page's whole
    // nav then pointed one level above the site root -- five dead links on the one page a reader
    // reaches by following a dead link.
    if (parts.length && parts[parts.length - 1].includes(".")) parts.pop();
    return parts.length === 0 ? "./" : "../".repeat(parts.length);
  },
};
