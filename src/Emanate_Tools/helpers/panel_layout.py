"""Shared panel drawing bits."""

# Left inset of a collapsible section's content, in separator() units: enough to
# clear the dropdown arrow, so the arrow stands alone in the margin.
SECTION_INDENT = 4.0


def indented(body):
    """A column inset from the left of `body`, to draw a collapsible section's content in.

    Blender draws a layout panel's content across the full panel width, further
    left than the section's own arrow. Layouts have no width of their own, so a
    fixed-width separator takes the margin and the column gets what is left.
    """
    row = body.row()
    row.separator(factor=SECTION_INDENT)
    return row.column()
