#!/usr/bin/python3
import argparse
import os
import queue
import threading
import rxv
import soco
import sys

from soco.events import event_listener


class Bridge:
    def __init__(self, amp, speaker, inp, vol):
        self.amp = amp
        self.speaker = speaker
        self._state = None
        self._hot = False
        self._input = inp
        self._volume = vol

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        if value == 'STOPPED' or value == 'PAUSED_PLAYBACK':
            self._hot = True
        elif value == 'PLAYING' and self._hot is True:
            try:
                self.switch_amp()
            except Exception as e:
                print('[E] error switching amp', e)
                self._hot = False

    def switch_amp(self):
        print('Switching amp to %s [@ %d]' % (self._input, self._volume))
        self.amp.input = self._input
        if self.amp.on is False:
            self.amp.on = True
        if self._volume is None:
            return
        if self.speaker.volume < self._volume:
            self.speaker.volume = self._volume


def collect_events(dev, out):
    sub = dev.avTransport.subscribe()
    while True:
        try:
            event = sub.events.get()
            out.put(event)
        except queue.Empty:
            break

    sub.unsubscribe()


def subscribe_one(device, mq):
    argv = (device, mq)
    t = threading.Thread(target=collect_events, args=argv)
    t.start()
    return t


def subscribe(devices):
    mq = queue.Queue()
    threads = [subscribe_one(d, mq) for d in devices]
    return mq, threads


def find_speakers(devices, name):
    lst = list(filter(lambda x: x.player_name == name, devices))
    return None if len(lst) != 1 else lst[0]


def handle_event(event, bridge):
    target = bridge.speaker
    player = event.service.soco
    state = event.variables.get('transport_state', None)
    if state is None:
        return

    in_group = target in player.group.members
    print('{:15}: {:15} {} {}'.format(player.player_name, state, in_group, player.is_coordinator))

    if player.is_coordinator is False or in_group is False:
        return

    bridge.state = state


def main():
    parser = argparse.ArgumentParser(description='automatically turn the amplifier on for sonos.')
    parser.add_argument('--sonos',  default='Living Room', help='sonso devices [Living Room]')
    parser.add_argument('--amplifier', default=None, help='amplifier to use [discover]')
    parser.add_argument('--input', default='AV5', help='amplifier input to use [AV4]')
    parser.add_argument('--volume', type=int, default=55, help='sonos volume to use [55]')
    args = parser.parse_args()

    amps = rxv.find()
    if args.amplifier is not None:
        lst = list(filter(lambda x: x.model_name == args.amplifier, amps))
        if len(lst) != 1:
            print('Could not find amplifier %s' % args.amplifier, file=sys.stderr)
            os.exit(1)
        amp = lst[0]
    else:
        amp = amps[0]
    print('Amplifier is %s' % amp.model_name)

    devices = soco.discover()
    for device in devices:
        print("%21s @ %s" % (device.player_name, device.ip_address))

    speaker = find_speakers(devices, args.sonos)
    if speaker is None:
        print('Could not find speaker %s' % args.sonso, file=sys.stderr)
        os.exit(1)

    print('Speaker is %s @ %s' % (speaker.player_name, speaker.ip_address))

    bridge = Bridge(amp, speaker, args.input, args.volume)

    # set up the unified queue
    mq, threads = subscribe(devices)

    keep_running = True
    while keep_running:
        try:
            event = mq.get()
            handle_event(event, bridge)

        except queue.Empty:
            pass
        except KeyboardInterrupt:
            keep_running = False

    event_listener.stop()


if __name__ == "__main__":
    main()
