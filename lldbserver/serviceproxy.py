
class LldbServiceProxy(object):

    def __init__(self, sender, listener):
        self.sender = sender
        self.listener = listener

    def __getattr__(self, name):
        def method_proxy(**args):
            message = {'command': name}
            message.update(args)
            self.sender(message)

        return method_proxy

    def notify_event(self, event):
        listener_method = getattr(self.listener, 'on_' + event['type'])
        args = event
        del args['type']
        listener_method(**args)
