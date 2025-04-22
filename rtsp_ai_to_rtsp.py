#!/usr/bin/env python3

################################################################################
# RTSP AI to RTSP script
# This script receives an RTSP stream, processes it with DeepStream AI,
# draws detected objects, and outputs to another RTSP stream
################################################################################

import sys
import argparse

sys.path.append("../")
from common.bus_call import bus_call
from common.platform_info import PlatformInfo
import pyds
from ctypes import *
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import datetime

# Constants
PGIE_CLASS_ID_VEHICLE = 0
PGIE_CLASS_ID_BICYCLE = 1
PGIE_CLASS_ID_PERSON = 2
PGIE_CLASS_ID_ROADSIGN = 3
MUXER_OUTPUT_WIDTH = 1920
MUXER_OUTPUT_HEIGHT = 1080
MUXER_BATCH_TIMEOUT_USEC = 33000
OSD_PROCESS_MODE = 0
OSD_DISPLAY_TEXT = 1
DEFAULT_BITRATE = 4000000  # 4Mbps

# pgie_src_pad_buffer_probe will extract metadata received on OSD sink pad
# and update params for drawing rectangle, object information etc.
def pgie_src_pad_buffer_probe(pad, info, u_data):
    frame_number = 0
    num_rects = 0
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("Unable to get GstBuffer ")
        return

    # Retrieve batch metadata from the gst_buffer
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break

        frame_number = frame_meta.frame_num
        num_detected_objects = 0
        l_obj = frame_meta.obj_meta_list
        while l_obj is not None:
            try:
                obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break

            # Update object text metadata with detection info
            obj_counter = {
                PGIE_CLASS_ID_VEHICLE: 0,
                PGIE_CLASS_ID_PERSON: 0,
                PGIE_CLASS_ID_BICYCLE: 0,
                PGIE_CLASS_ID_ROADSIGN: 0
            }
            obj_counter[obj_meta.class_id] += 1
            num_detected_objects += 1

            # Get class name from object meta
            if obj_meta.class_id == PGIE_CLASS_ID_VEHICLE:
                obj_meta.text_params.display_text = "Vehicle {:.2f}".format(obj_meta.confidence)
            elif obj_meta.class_id == PGIE_CLASS_ID_PERSON:
                obj_meta.text_params.display_text = "Person {:.2f}".format(obj_meta.confidence)
            elif obj_meta.class_id == PGIE_CLASS_ID_BICYCLE:
                obj_meta.text_params.display_text = "TwoWheeler {:.2f}".format(obj_meta.confidence)
            elif obj_meta.class_id == PGIE_CLASS_ID_ROADSIGN:
                obj_meta.text_params.display_text = "RoadSign {:.2f}".format(obj_meta.confidence)

            # Set text font and color
            obj_meta.text_params.font_params.font_name = "Arial"
            obj_meta.text_params.font_params.font_size = 14
            obj_meta.text_params.font_params.font_color.set(1.0, 1.0, 0.0, 1.0)
            obj_meta.text_params.set_bg_clr = 1
            obj_meta.text_params.text_bg_clr.set(0.0, 0.0, 0.0, 0.5)

            try:
                l_obj = l_obj.next
            except StopIteration:
                break

        # Print frame stats
        # print("Frame Number={}, Number of Objects={}".format(frame_number, num_detected_objects))
        
        # Display timestamp if enabled
        if u_data:  # If timestamp display is enabled
            ts = frame_meta.ntp_timestamp/1000000000
            print("RTSP Timestamp:", datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'))

        try:
            l_frame = l_frame.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK

def cb_newpad(decodebin, decoder_src_pad, data):
    print("In cb_newpad\n")
    caps = decoder_src_pad.get_current_caps()
    gststruct = caps.get_structure(0)
    gstname = gststruct.get_name()
    source_bin = data
    features = caps.get_features(0)

    print("gstname=", gstname)
    if gstname.find("video") != -1:
        print("features=", features)
        if features.contains("memory:NVMM"):
            # Get the source bin ghost pad
            bin_ghost_pad = source_bin.get_static_pad("src")
            if not bin_ghost_pad.set_target(decoder_src_pad):
                sys.stderr.write("Failed to link decoder src pad to source bin ghost pad\n")
        else:
            sys.stderr.write("Error: Decodebin did not pick nvidia decoder plugin.\n")

def decodebin_child_added(child_proxy, Object, name, user_data):
    print("Decodebin child added:", name,)
    if name.find("decodebin") != -1:
        Object.connect("child-added", decodebin_child_added, user_data)

    # if user_data:  # If timestamp from RTSP is enabled
    #     if name.find("source") != -1:
    #         pyds.configure_source_for_ntp_sync(hash(Object))

def create_source_bin(index, uri):
    print("Creating source bin")

    bin_name = "source-bin-%02d" % index
    print(bin_name)
    nbin = Gst.Bin.new(bin_name)
    if not nbin:
        sys.stderr.write("Unable to create source bin\n")
        return None

    uri_decode_bin = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
    if not uri_decode_bin:
        sys.stderr.write("Unable to create uri decode bin\n")
        return None

    # Set properties
    uri_decode_bin.set_property("uri", uri)
    uri_decode_bin.set_property("buffer-size", 4096)  # Increase RTSP buffer
    uri_decode_bin.set_property("buffer-duration", 500000000)  # 500ms buffer

    # Connect signals
    uri_decode_bin.connect("pad-added", cb_newpad, nbin)
    uri_decode_bin.connect("child-added", decodebin_child_added, nbin)

    # Add to bin and create ghost pad
    Gst.Bin.add(nbin, uri_decode_bin)
    bin_pad = nbin.add_pad(Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC))
    if not bin_pad:
        sys.stderr.write("Failed to add ghost pad in source bin\n")
        return None
        
    return nbin

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="RTSP AI to RTSP Processing")
    parser.add_argument("--input-rtsp", required=True, help="Input RTSP URL")
    parser.add_argument("--output-rtsp", required=True, help="Output RTSP URL")
    parser.add_argument("--config-file", default="dstest1_pgie_config.txt", 
                        help="Path to config file for primary inference")
    parser.add_argument("--gie", default="nvinfer", choices=['nvinfer', 'nvinferserver'],
                        help="GPU inference engine type (nvinfer or nvinferserver)")
    parser.add_argument("--codec", default="H264", choices=['H264', 'H265'],
                        help="RTSP Streaming Codec")
    parser.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE,
                        help=f"Encoding bitrate in bits/second (default: {DEFAULT_BITRATE})")
    parser.add_argument("--rtsp-ts", action="store_true", default=False,
                        help="Attach NTP timestamp from RTSP source")
    
    args = parser.parse_args()
    
    # Print configuration
    print(f"Input RTSP: {args.input_rtsp}")
    print(f"Output RTSP: {args.output_rtsp}")
    print(f"Inference Engine: {args.gie}")
    print(f"Codec: {args.codec}")
    print(f"Bitrate: {args.bitrate}")
    print(f"Config File: {args.config_file}")
    # print(f"RTSP Timestamp: {args.rtsp_ts}")
    
    # Initialize GStreamer
    Gst.init(None)
    
    # Create platform info object
    platform_info = PlatformInfo()
    
    # Create pipeline
    pipeline = Gst.Pipeline()
    if not pipeline:
        sys.stderr.write("Unable to create Pipeline\n")
        return -1
    
    # Create source bin for RTSP input
    source_bin = create_source_bin(0, args.input_rtsp)
    if not source_bin:
        sys.stderr.write("Unable to create source bin\n")
        return -1
    
    # Create streammux
    streammux = Gst.ElementFactory.make("nvstreammux", "stream-muxer")
    if not streammux:
        sys.stderr.write("Unable to create NvStreamMux\n")
        return -1
    
    # Set streammux properties
    streammux.set_property("width", MUXER_OUTPUT_WIDTH)
    streammux.set_property("height", MUXER_OUTPUT_HEIGHT)
    streammux.set_property("batch-size", 1)
    streammux.set_property("batched-push-timeout", MUXER_BATCH_TIMEOUT_USEC)
    if args.rtsp_ts:
        streammux.set_property("attach-sys-ts", 0)
    
    # Create primary inference (GIE) element
    if args.gie == "nvinfer":
        pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
        pgie.set_property("config-file-path", args.config_file)
    else:
        pgie = Gst.ElementFactory.make("nvinferserver", "primary-inference")
        pgie.set_property("config-file-path", args.config_file)
    if not pgie:
        sys.stderr.write(f"Unable to create {args.gie} element\n")
        return -1
    
    # Create video converter for encoder input
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "converter")
    if not nvvidconv:
        sys.stderr.write("Unable to create nvvideoconvert\n")
        return -1
    
    # Create on-screen display
    nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
    if not nvosd:
        sys.stderr.write("Unable to create nvdsosd\n")
        return -1
    
    # Set OSD properties
    nvosd.set_property("process-mode", OSD_PROCESS_MODE)
    nvosd.set_property("display-text", OSD_DISPLAY_TEXT)
    
    
    # Create video converter for post-OSD processing
    nvvidconv_postosd = Gst.ElementFactory.make(
        "nvvideoconvert", "convertor_postosd")
    if not nvvidconv_postosd:
        sys.stderr.write(" Unable to create nvvidconv_postosd \n")


    # Create capsfilter to set video format
    capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
    if not capsfilter:
        sys.stderr.write("Unable to create capsfilter\n")
        return -1
    caps = Gst.Caps.from_string("video/x-raw(memory:NVMM), format=I420")
    capsfilter.set_property("caps", caps)

    # Create encoder based on codec selection
    if args.codec == "H264":
        encoder = Gst.ElementFactory.make("nvv4l2h264enc", "encoder")
        print("Creating H264 Encoder")
    elif args.codec == "H265":
        encoder = Gst.ElementFactory.make("nvv4l2h265enc", "encoder")
        print("Creating H265 Encoder")
    
    if not encoder:
        sys.stderr.write("Unable to create encoder\n")
        return -1
    
    # Set encoder properties
    encoder.set_property("bitrate", args.bitrate)
    if platform_info.is_integrated_gpu():
        encoder.set_property("preset-level", 1)
        encoder.set_property("insert-sps-pps", 1)
    
    # Create RTP parser
    if args.codec == "H264":
        parser = Gst.ElementFactory.make("h264parse", "h264parser")
    elif args.codec == "H265":
        parser = Gst.ElementFactory.make("h265parse", "h265parse")
    
    if not parser:
        sys.stderr.write("Unable to create parser\n")
        return -1

    # Create RTSP sink - directly use rtspclientsink without fallback
    rtsp_sink = Gst.ElementFactory.make("rtspclientsink", "rtsp-sink")
    if not rtsp_sink:
        sys.stderr.write("Unable to create rtspclientsink. Make sure gst-rtsp-server is installed.\n")
        return -1
        
    # Set RTSP sink properties
    rtsp_sink.set_property("location", args.output_rtsp)
    
    # Add all elements to pipeline
    pipeline.add(source_bin)
    pipeline.add(streammux)
    pipeline.add(pgie)
    pipeline.add(nvvidconv)
    pipeline.add(nvosd)
    pipeline.add(nvvidconv_postosd)
    pipeline.add(capsfilter)
    pipeline.add(encoder)
    pipeline.add(parser)
    pipeline.add(rtsp_sink)


    # Link source to streammux
    padname = "sink_0"
    sinkpad = streammux.request_pad_simple(padname)
    if not sinkpad:
        sys.stderr.write("Unable to get sink pad of streammux\n")
        return -1
    
    srcpad = source_bin.get_static_pad("src")
    if not srcpad:
        sys.stderr.write("Unable to get src pad of source bin\n")
        return -1
    
    srcpad.link(sinkpad)
    
    # Link all elements
    streammux.link(pgie) # nvstreammux -> nvinfer
    pgie.link(nvvidconv) # nvinfer -> nvdsosd
    nvvidconv.link(nvosd) # nvdsosd -> nvvideoconvert
    nvosd.link(nvvidconv_postosd) # nvvideoconvert -> nvvideoconvert
    nvvidconv_postosd.link(capsfilter) # nvvideoconvert -> capsfilter
    capsfilter.link(encoder) # capsfilter -> nvv4l2h264enc
    encoder.link(parser) # nvv4l2h264enc -> h264parse
    parser.link(rtsp_sink) # h264parse -> rtspclientsink


    # Add probe to get inference output
    pgie_src_pad = pgie.get_static_pad("src")
    if not pgie_src_pad:
        sys.stderr.write("Unable to get src pad of pgie\n")
        return -1
    
    pgie_src_pad.add_probe(Gst.PadProbeType.BUFFER, pgie_src_pad_buffer_probe, args.rtsp_ts)
    
    # Create an event loop and feed gstreamer bus messages to it
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)
    
    # Start pipeline
    print("Starting pipeline\n")
    print(f"\n *** DeepStream: Streaming to RTSP output: {args.output_rtsp} ***\n")
    pipeline.set_state(Gst.State.PLAYING)
    
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error running pipeline: {e}")
    finally:
        # Clean up
        pipeline.set_state(Gst.State.NULL)
        print("Pipeline stopped")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())