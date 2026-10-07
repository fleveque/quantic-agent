"""A local agent that drafts data-grounded content for Quantic.

Every figure the agent writes traces to a recorded tool call, and nothing it
drafts is published without a human (docs/design.md, N1 and N2). This package
is an application, not a library: its modules are here to read, not to import
from another project.
"""
