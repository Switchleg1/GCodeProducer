"""Compute worker result dispatch in the GUI process."""

MESSAGE_HANDLERS = {
    'log': '_receive_log',
    'progress': '_receive_progress',
    'chunk': '_receive_chunk',
    'done': '_receive_done',
    'error': '_receive_error',
}
