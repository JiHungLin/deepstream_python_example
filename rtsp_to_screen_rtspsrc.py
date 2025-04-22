#!/usr/bin/env python3
import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

# 初始化GStreamer
Gst.init(None)

def on_pad_added(src, new_pad, depay):
    """Callback function for handling dynamic pad creation"""
    print("Received new pad {} from {}".format(new_pad.get_name(), src.get_name()))
    
    # Check if our depay element already has a source pad connected
    sink_pad = depay.get_static_pad("sink")
    if sink_pad.is_linked():
        print("We are already linked. Ignoring.")
        return
        
    # Check the new pad's type
    new_pad_caps = new_pad.get_current_caps()
    if not new_pad_caps:
        print("Pad has no caps, ignoring")
        return
    
    new_pad_struct = new_pad_caps.get_structure(0)
    new_pad_type = new_pad_struct.get_name()
    
    print("Pad type: {}".format(new_pad_type))
    
    # Link if it's an RTP pad with supported encoding
    if new_pad_type.startswith("application/x-rtp"):
        encoding_name = new_pad_struct.get_string("encoding-name")
        print(f"Found encoding: {encoding_name}")
        
        # Attempt to link regardless of encoding type - let GStreamer handle compatibility
        print(f"Linking pad with encoding {encoding_name}")
        if new_pad.link(sink_pad) == Gst.PadLinkReturn.OK:
            print("Link successful")
        else:
            print("Link failed")
        
def bus_call(bus, message, loop):
    """Callback for handling GStreamer bus messages"""
    t = message.type
    if t == Gst.MessageType.EOS:
        print("End-of-stream")
        loop.quit()
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print("Error: {}: {}".format(err, debug))
        loop.quit()
    return True

def main(args):
    # 設置源RTSP URL
    src_rtsp_url = "rtsp://192.168.1.222:8554/test_stream1"
    
    # 創建GStreamer管道
    pipeline = Gst.Pipeline()
    
    # 創建元素
    # RTSP源
    src = Gst.ElementFactory.make("rtspsrc", "source")
    if not src:
        sys.stderr.write(" Unable to create rtspsrc \n")
        return -1
    src.set_property("location", src_rtsp_url)
    src.set_property("latency", 0)  # Reduce latency
    src.set_property("protocols", 4)  # Use TCP (4) to avoid UDP issues
    src.set_property("buffer-mode", 0)  # Buffer mode: auto
    src.set_property("retry", 10)  # Number of retries before giving up
    src.set_property("timeout", 5000000)  # Timeout in microseconds
    
    # Use more generic depayloader for MPEG4
    depay = Gst.ElementFactory.make("rtpmp4vdepay", "depay")
    if not depay:
        sys.stderr.write(" Unable to create rtpmp4vdepay \n")
        return -1
        
    # Parse the MPEG4 stream
    parse = Gst.ElementFactory.make("mpeg4videoparse", "parse")
    if not parse:
        sys.stderr.write(" Unable to create mpeg4videoparse \n")
        return -1
        
    # Decode the MPEG4 stream
    dec = Gst.ElementFactory.make("avdec_mpeg4", "decoder") 
    if not dec:
        # Try hardware decoder as fallback
        dec = Gst.ElementFactory.make("nvv4l2decoder", "decoder")
        if not dec:
            sys.stderr.write(" Unable to create decoder \n")
            return -1
    
    # Convert video format
    videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")
    if not videoconvert:
        sys.stderr.write(" Unable to create videoconvert \n")
        return -1
        
    # Create display sink
    sink = Gst.ElementFactory.make("autovideosink", "sink")
    if not sink:
        sys.stderr.write(" Unable to create autovideosink \n")
        return -1
    
    # Add all elements to the pipeline
    pipeline.add(src)
    pipeline.add(depay)
    pipeline.add(parse)
    pipeline.add(dec)
    pipeline.add(videoconvert)
    pipeline.add(sink)
    
    # Link static elements - we can't link src yet as it creates dynamic pads
    depay.link(parse)
    parse.link(dec)
    dec.link(videoconvert)
    videoconvert.link(sink)
    
    # Connect to the pad-added signal for rtspsrc
    src.connect("pad-added", on_pad_added, depay)
    
    # Create a bus and connect it
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    loop = GLib.MainLoop()
    bus.connect("message", bus_call, loop)
    
    # Start playing
    pipeline.set_state(Gst.State.PLAYING)
    
    try:
        print(f"RTSP stream started: {src_rtsp_url}")
        loop.run()
    except KeyboardInterrupt:
        print("接收到中斷信號，清理...")
    
if __name__ == "__main__":
    sys.exit(main(sys.argv))