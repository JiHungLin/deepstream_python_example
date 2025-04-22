#!/usr/bin/env python3
# 檔名: rtsp_to_rtmp.py
# 功能: 將RTSP影像串流轉換成RTMP串流

import sys
import argparse
sys.path.append("../")
from common.bus_call import bus_call
from common.platform_info import PlatformInfo
from ctypes import *
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib


MUXER_OUTPUT_WIDTH = 1920
MUXER_OUTPUT_HEIGHT = 1080
MUXER_BATCH_TIMEOUT_USEC = 10000
DEFAULT_BITRATE = 2000  # kbps

def cb_newpad(decodebin, decoder_src_pad, data):
    print("In cb_newpad\n")
    caps = decoder_src_pad.get_current_caps()
    gststruct = caps.get_structure(0)
    gstname = gststruct.get_name()
    source_bin = data
    features = caps.get_features(0)

    # Need to check if the pad created by the decodebin is for video and not
    # audio.
    print("gstname=", gstname)
    if gstname.find("video") != -1:
        # Link the decodebin pad only if decodebin has picked nvidia
        # decoder plugin nvdec_*. We do this by checking if the pad caps contain
        # NVMM memory features.
        print("features=", features)
        if features.contains("memory:NVMM"):
            # Get the source bin ghost pad
            bin_ghost_pad = source_bin.get_static_pad("src")
            if not bin_ghost_pad.set_target(decoder_src_pad):
                sys.stderr.write(
                    "Failed to link decoder src pad to source bin ghost pad\n"
                )
        else:
            sys.stderr.write(
                " Error: Decodebin did not pick nvidia decoder plugin.\n")


def decodebin_child_added(child_proxy, Object, name, user_data):
    print("Decodebin child added:", name, "\n")
    if name.find("decodebin") != -1:
        Object.connect("child-added", decodebin_child_added, user_data)

def create_source_bin(index, uri):
    print("Creating source bin")

    # Create a source GstBin to abstract this bin's content from the rest of the
    # pipeline
    bin_name = "source-bin-%02d" % index
    print(bin_name)
    nbin = Gst.Bin.new(bin_name)
    if not nbin:
        sys.stderr.write(" Unable to create source bin \n")

    # Source element for reading from the uri.
    # We will use decodebin and let it figure out the container format of the
    # stream and the codec and plug the appropriate demux and decode plugins.
    uri_decode_bin = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
    if not uri_decode_bin:
        sys.stderr.write(" Unable to create uri decode bin \n")
    # We set the input uri to the source element
    uri_decode_bin.set_property("uri", uri)
    uri_decode_bin.set_property("buffer-size", 4096)  # 增加 RTSP 緩衝區
    uri_decode_bin.set_property("buffer-duration", 500000000)  # 500ms 緩衝
    # Connect to the "pad-added" signal of the decodebin which generates a
    # callback once a new pad for raw data has beed created by the decodebin
    uri_decode_bin.connect("pad-added", cb_newpad, nbin)
    uri_decode_bin.connect("child-added", decodebin_child_added, nbin)

    # We need to create a ghost pad for the source bin which will act as a proxy
    # for the video decoder src pad. The ghost pad will not have a target right
    # now. Once the decode bin creates the video decoder and generates the
    # cb_newpad callback, we will set the ghost pad target to the video decoder
    # src pad.
    Gst.Bin.add(nbin, uri_decode_bin)
    bin_pad = nbin.add_pad(
        Gst.GhostPad.new_no_target(
            "src", Gst.PadDirection.SRC))
    if not bin_pad:
        sys.stderr.write(" Failed to add ghost pad in source bin \n")
        return None
    return nbin


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="將RTSP串流轉換成RTMP串流")
    parser.add_argument("--rtsp-url", required=True, help="RTSP 來源網址，例如 rtsp://192.168.1.123:8554/stream")
    parser.add_argument("--rtmp-url", required=True, help="RTMP 目標網址，例如 rtmp://192.168.1.123/live/stream")
    parser.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE, help=f"影像位元率 (kbps)，預設 {DEFAULT_BITRATE}")
    parser.add_argument("--width", type=int, default=MUXER_OUTPUT_WIDTH, help=f"輸出影像寬度，預設 {MUXER_OUTPUT_WIDTH}")
    parser.add_argument("--height", type=int, default=MUXER_OUTPUT_HEIGHT, help=f"輸出影像高度，預設 {MUXER_OUTPUT_HEIGHT}")
    
    args = parser.parse_args()
    
    rtsp_url = args.rtsp_url
    rtmp_url = args.rtmp_url
    bitrate = args.bitrate
    width = args.width
    height = args.height
    
    print(f"RTSP 來源: {rtsp_url}")
    print(f"RTMP 目標: {rtmp_url}")
    print(f"設定影像大小: {width}x{height}, 位元率: {bitrate}kbps")
    
    # 初始化 GStreamer
    Gst.init(None)
    
    # 建立管道
    pipeline = Gst.Pipeline()
    if not pipeline:
        sys.stderr.write(" 無法建立管道")
        return -1
    
    # 建立來源
    print("建立 RTSP 來源")
    source_bin = create_source_bin(0, rtsp_url)
    if not source_bin:
        sys.stderr.write("無法建立來源 bin\n")
        return -1
    
    # 建立串流複用器
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    if not streammux:
        sys.stderr.write(" 無法建立 NvStreamMux\n")
        return -1
    
    # 設定 streammux 屬性
    streammux.set_property("width", width)
    streammux.set_property("height", height)
    streammux.set_property("batch-size", 1)  # 只有一個來源
    streammux.set_property("batched-push-timeout", MUXER_BATCH_TIMEOUT_USEC)
    streammux.set_property("buffer-pool-size", 8)
    
    # 建立影像轉換和解碼元件
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    if not nvvidconv:
        sys.stderr.write(" 無法建立 nvvideoconvert\n")
        return -1
    
    # 建立 H264 編碼器
    encoder = Gst.ElementFactory.make("nvv4l2h264enc", "encoder")
    if not encoder:
        print("無法建立 nvv4l2h264enc 元素，嘗試使用 nvh264enc...")
        encoder = Gst.ElementFactory.make("nvh264enc", "encoder")
        if not encoder:
            print("無法建立 nvh264enc 元素，嘗試使用 x264enc...")
            encoder = Gst.ElementFactory.make("x264enc", "encoder")
            if not encoder:
                print("無法建立任何 H264 編碼器，請安裝所需的 GStreamer 外掛")
                return -1
    
    # 設定編碼器參數
    if encoder.get_factory().get_name() == "nvv4l2h264enc":
        # nvv4l2h264enc 參數設定 (用於 Jetson)
        encoder.set_property("bitrate", bitrate * 1000)  # 以 bits/sec 為單位
    elif encoder.get_factory().get_name() == "nvh264enc":
        # nvh264enc 參數設定 (用於 dGPU)
        encoder.set_property("bitrate", bitrate)  # 以 Kbits/sec 為單位
        encoder.set_property("preset", 1)  # 0=slow, 1=medium, 2=fast
        encoder.set_property("rc-mode", 1)  # 1=cbr, 2=vbr
    else:
        # x264enc 參數設定 (軟體編碼)
        encoder.set_property("bitrate", bitrate)
        encoder.set_property("speed-preset", "medium")
        encoder.set_property("tune", "zerolatency")
    
    print(f"使用 {encoder.get_factory().get_name()} 編碼器")
    
    # 建立 H264 parser
    h264parser = Gst.ElementFactory.make("h264parse", "h264parser")
    if not h264parser:
        sys.stderr.write(" 無法建立 h264parse\n")
        return -1
    
    # 建立 FLV muxer 和 RTMP sink
    flvmux = Gst.ElementFactory.make("flvmux", "flvmux")
    if not flvmux:
        sys.stderr.write(" 無法建立 flvmux\n")
        return -1
    
    rtmpsink = Gst.ElementFactory.make("rtmpsink", "rtmpsink")
    if not rtmpsink:
        sys.stderr.write(" 無法建立 rtmpsink\n")
        return -1
    
    rtmpsink.set_property("location", rtmp_url)
    
    # 將元件添加到管道中
    pipeline.add(source_bin)
    pipeline.add(streammux)
    pipeline.add(nvvidconv)
    pipeline.add(encoder)
    pipeline.add(h264parser)
    pipeline.add(flvmux)
    pipeline.add(rtmpsink)
    
    # 連接 RTSP 來源到 streammux
    padname = "sink_0"
    sinkpad = streammux.request_pad_simple(padname)
    if not sinkpad:
        sys.stderr.write(" 無法請求 streammux sink pad\n")
        return -1
    
    srcpad = source_bin.get_static_pad("src")
    if not srcpad:
        sys.stderr.write(" 無法取得 source bin src pad\n")
        return -1
    
    srcpad.link(sinkpad)
    
    # 連接剩餘元件
    streammux.link(nvvidconv)
    nvvidconv.link(encoder)
    encoder.link(h264parser)
    h264parser.link(flvmux)
    flvmux.link(rtmpsink)
    
    # 建立事件循環並監聽 GStreamer 訊息
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)
    
    # 啟動管道
    print("開始串流轉換...")
    pipeline.set_state(Gst.State.PLAYING)
    
    try:
        loop.run()
    except KeyboardInterrupt:
        print("使用者中斷，停止串流...")
    finally:
        # 清理
        pipeline.set_state(Gst.State.NULL)
        print("串流已停止")

if __name__ == "__main__":
    sys.exit(main())
