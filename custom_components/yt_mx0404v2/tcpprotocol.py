import asyncio
import logging
from collections import deque

class MX0404V2TCP(asyncio.Protocol):
    """MX0404 via TCP protocol."""

    transport = None

    def __init__(self, client, loop, disconnect_callback=None, logger=None):
        """Initialize the USR-R16 protocol."""
        self.client = client
        self.loop = loop
        self.logger = logger
        self._buffer = b''
        self.check_status_cmd = "bc "
        self.status = {}
        self.disconnect_callback = disconnect_callback
        self._timeout = None
        self._cmd_timeout = None

    def connection_made(self, transport):
        """Initialize protocol transport."""
        self.transport = transport
        self._reset_timeout()
    
    def _reset_timeout(self):
        """Reset timeout for date keep alive."""
        if self._timeout:
            self._timeout.cancel()
        self._timeout = self.loop.call_later(
            self.client.timeout, self.transport.close)
        self.logger.debug(f'timeout reset')

    def reset_cmd_timeout(self):
        """Reset timeout for command execution."""
        if self._cmd_timeout:
            self._cmd_timeout.cancel()
        self._cmd_timeout = self.loop.call_later(
            self.client.timeout, self.transport.close)
        self.logger.debug(f'cmd timeout reset')

    def data_received(self, data):
        """Add incoming data to buffer."""
        try:
            self.logger.debug(f"Received: {data.decode()}")
        except:
            self.logger.debug(f"Received: {data}")
        self._buffer = data
        self.handle_buffer()

    def handle_buffer(self):
        """Assemble incoming data into per-line packets."""
        self._reset_timeout()
        changes = []
        if self._buffer.startswith(b's'):
            if len(self._buffer) == 5:
                if self._buffer[1] == 0 and self._buffer[2] == 3:
                    changes.append(1)
                elif self._buffer[1] == 10 and self._buffer[2] == 2:
                    changes.append(2)
            else:
                for state in self._buffer.splitlines():
                    try:
                        state = state.decode("utf-8")
                        self.status_update(state)
                        changes=[1, 2, 3, 4]
                    except:
                        self.logger.debug(f"Received unknown status: {state}")
        for outp in changes:
            for status_cb in self.client.status_callbacks.get(outp, []):
                status_cb(self.status[f'o{outp}'])
        self.logger.debug(f'current states are {self.status}')
        if self.client.in_transaction:
            self.client.in_transaction = False
            self.client.active_packet = None
            self.client.active_transaction.set_result(self.status)
            while self.client.status_waiters:
                waiter = self.client.status_waiters.popleft()
                waiter.set_result(self.status)
            if self.client.waiters:
                self.send_packet()
            else:
                self._cmd_timeout.cancel()
        elif self._cmd_timeout:
            self._cmd_timeout.cancel()
        self._reset_timeout()
    
    def status_update(self, state):
        if len(state) == 3:
            output_num = int(state[1])
            input_num = int(state[2])+1
            if output_num == 1:
                self.status["o1"] = input_num
            elif output_num == 2:
                self.status["o2"] = input_num
            elif output_num == 3:
                self.status["o3"] = input_num
            elif output_num == 4:
                self.status["o4"] = input_num
        else:
            self.logger.error("wrong state")

    def send_packet(self):
        """Write next packet in send queue."""
        waiter, packet = self.client.waiters.popleft()
        self.logger.debug('sending packet: %s', packet.hex())
        self.client.active_transaction = waiter
        self.client.in_transaction = True
        self.client.active_packet = packet
        self.reset_cmd_timeout()
        self.transport.write(packet)
    
    def create_packet(self, cmd):
        """Cmd format as [output][input], all int or input could be +/-"""
        output = cmd[0]
        input = cmd[1]
        basic_cmd = "cir "
        input_isnum = False
        if input == "+":
            l = "e" if output % 2 == 1 else "6"
        elif input == "-":
            l = "d" if output % 2 == 1 else "5"
        else:
            input_isnum = True
            l = hex(input - 1)[2:] if output % 2 == 1 else hex(input + 7)[2:]
        h = str(output // 3) if input_isnum else str(int(not bool(output // 2 % 2)))
        return(self.format_cmd(basic_cmd + h + l))

    def format_cmd(self, cmd):
        return cmd.encode("ascii") + b"\r" + b"\n"

    def connection_lost(self, exc):
        """Log when connection is closed, if needed call callback."""
        if exc:
            self.logger.error('disconnected due to error')
        else:
            self.logger.info('disconnected because of close/abort.')
        if self.disconnect_callback:
            asyncio.ensure_future(self.disconnect_callback(), loop=self.loop)


class MX0404V2TCPClient:
    """MX0404 tcp client wrapper class."""

    def __init__(self, host, port=23,
                 disconnect_callback=None, reconnect_callback=None,
                 loop=None, logger=None, timeout=10, polling_interval=2, reconnect_interval=10):
        """Initialize the MX0404 client wrapper."""
        if loop:
            self.loop = loop
        else:
            self.loop = asyncio.get_event_loop()
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)

        self.host = host
        self.port = port
        self.timeout = timeout
        self.polling_interval = polling_interval
        self.reconnect = True
        self.reconnect_interval = reconnect_interval
        self.reconnect_callback = reconnect_callback
        self.disconnect_callback = disconnect_callback
        self.transport = None
        self.protocol = None
        self.is_connected = False
        self.waiters = deque()
        self.status_waiters = deque()
        self.active_transaction = None
        self.in_transaction = False
        self.active_packet = None
        self.states = {}
        self.status_callbacks = {}

    async def setup(self):
        """Set up the connection, automatic retry and get status."""
        while True:
            fut = self.loop.create_connection(
                lambda: MX0404V2TCP(
                    self,
                    disconnect_callback=self.handle_disconnect_callback,
                    loop=self.loop, logger=self.logger),
                host=self.host,
                port=self.port)
            try:
                self.transport, self.protocol = \
                    await asyncio.wait_for(fut, timeout=self.timeout)
            except asyncio.TimeoutError:
                self.logger.warning("Could not connect due to timeout error.")
            except OSError as exc:
                self.logger.warning("Could not connect due to error: %s",
                                    str(exc))
            else:
                self.is_connected = True
                self.states = await self.status()
                asyncio.ensure_future(self.poll())
                if self.reconnect and self.reconnect_callback:
                    self.reconnect_callback()
                break
            await asyncio.sleep(self.reconnect_interval)

    def register_status_callback(self, callback, output):
        """Register a callback which will fire when state changes."""
        if self.status_callbacks.get(output, None) is None:
            self.status_callbacks[output] = []
        self.status_callbacks[output].append(callback)

    def stop(self):
        """Shut down transport."""
        self.reconnect = False
        self.logger.debug("Shutting down.")
        if self.transport:
            self.transport.close()

    def _send(self, packet):
        """Add packet to send queue."""
        fut = self.loop.create_future()
        self.waiters.append((fut, packet))
        if self.waiters and self.in_transaction is False:
            self.protocol.send_packet()
        return fut
    
    async def poll(self):
        while True:
            await self.status()
            await asyncio.sleep(self.polling_interval)

    async def handle_disconnect_callback(self):
        """Reconnect automatically unless stopping."""
        self.is_connected = False
        if self.disconnect_callback:
            self.disconnect_callback()
        if self.reconnect:
            self.logger.debug("Protocol disconnected...reconnecting")
            await self.setup()
            self.protocol.reset_cmd_timeout()
            if self.in_transaction:
                self.protocol.transport.write(self.active_packet)
            else:
                await self.status()

    async def status(self):
        """Get current output status."""
        if self.waiters or self.in_transaction:
            fut = self.loop.create_future()
            self.status_waiters.append(fut)
            state = await fut
        else:
            packet = self.protocol.format_cmd(self.protocol.check_status_cmd)
            state = await self._send(packet)
            await asyncio.sleep(0.5)
        return state

    async def select_output(self, outp, inp):
        packet = self.protocol.create_packet([outp,inp])
        states = await self._send(packet)
        await asyncio.sleep(0.5)
        return states

async def create_mx0404_client_connection(host=None, port=None,
                                           disconnect_callback=None,
                                           reconnect_callback=None, loop=None,
                                           logger=None, timeout=None,
                                           polling_interval=None,
                                           reconnect_interval=None):
    """Create MX0404 Client class."""
    client = MX0404V2TCPClient(host, port=port, 
                         disconnect_callback=disconnect_callback,
                         reconnect_callback=reconnect_callback,
                         loop=loop, logger=logger, polling_interval=polling_interval,
                         timeout=timeout, reconnect_interval=reconnect_interval)
    await client.setup()

    return client
