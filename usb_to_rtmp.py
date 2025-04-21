#!/usr/bin/env python3
# 檔名: usb_to_rtmp.py
# 功能: 將USB網路攝影機影像串流轉成H264播放

import argparse
import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
import subprocess
import re

def list_all_devices():
    """列出所有可用的USB攝影機設備，使用v4l2-ctl查詢"""
    
    try:
        # 執行v4l2-ctl --list-devices命令
        result = subprocess.run(['v4l2-ctl', '--list-devices'], 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE,
                               text=True)
        
        if result.returncode != 0:
            print(f"v4l2-ctl命令執行失敗: {result.stderr}")
            return []
        
        # 使用正則表達式找出所有/dev/video開頭的設備路徑
        devices = re.findall(r'/dev/video\d+', result.stdout)
        return devices
    
    except FileNotFoundError:
        print("找不到v4l2-ctl工具，請先安裝v4l-utils套件")
        return []
    except Exception as e:
        print(f"查詢設備時出錯: {e}")
        return []

def show_device_capabilities(device):
    """顯示指定設備的詳細資訊"""
    try:
        # 執行v4l2-ctl --list-formats-ext命令來獲取設備支援的格式資訊
        result = subprocess.run(['v4l2-ctl', '--device', device, '--list-formats-ext'], 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE,
                               text=True)
        
        if result.returncode != 0:
            print(f"無法獲取設備 {device} 的資訊: {result.stderr}")
            return
        
        # 顯示結果
        print(result.stdout)
    except FileNotFoundError:
        print("找不到v4l2-ctl工具，請先安裝v4l-utils套件")
    except Exception as e:
        print(f"查詢設備資訊時出錯: {e}")

def main_pipeline(device, width, height, fps, bitrate, rtmp_url=None):
    """建立GStreamer管道"""
    # 初始化GStreamer
    Gst.init(None)
        
    # 建立GStreamer管道
    pipeline = Gst.Pipeline()

    # 建立元素
    source = Gst.ElementFactory.make("v4l2src", "source")
    if not source:
        print("無法建立source元素，可能需要安裝對應的GStreamer外掛")
        return None
    source.set_property("device", device)
    print(f"使用設備: {device}")
    
    # 設定格式為YUY2
    capsfilter1 = Gst.ElementFactory.make("capsfilter", "capsfilter1")
    if not capsfilter1:
        print("無法建立capsfilter元素，可能需要安裝對應的GStreamer外掛")
        return None
    caps1 = Gst.Caps.from_string(f"video/x-raw,width={width},height={height},framerate={fps}/1")
    
    capsfilter1.set_property("caps", caps1)
    print(f"設定影像格式: {width}x{height}, {fps}fps")

    vidconvsrc = Gst.ElementFactory.make("videoconvert", "convertor_src1")
    if not vidconvsrc:
        sys.stderr.write(" Unable to create videoconvert \n")

    
    # NVIDIA影像轉換器
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "nvvidconv")
    if not nvvidconv:
        print("無法建立nvvidconv元素，可能需要安裝對應的GStreamer外掛")
        return None
    
    # 嘗試使用NVIDIA硬體H264編碼器 (優先順序)
    # 1. nvv4l2h264enc - NVIDIA V4L2 based hardware encoder for Jetson
    # 2. nvh264enc - NVIDIA GPU based encoder for dGPU platforms
    # 3. x264enc - Software encoder as fallback
    encoder = Gst.ElementFactory.make("nvv4l2h264enc", "encoder")
    if not encoder:
        print("無法建立nvv4l2h264enc元素，嘗試使用nvh264enc...")
        encoder = Gst.ElementFactory.make("nvh264enc", "encoder")
        if not encoder:
            print("無法建立nvh264enc元素，嘗試使用x264enc...")
            encoder = Gst.ElementFactory.make("x264enc", "encoder")
            if not encoder:
                print("無法建立任何H264編碼器，請安裝所需的GStreamer外掛")
                return None
    
    # 設定編碼器參數 (根據不同編碼器調整參數)
    if encoder.get_factory().get_name() == "nvv4l2h264enc":
        # nvv4l2h264enc 參數設定 (用於 Jetson)
        encoder.set_property("bitrate", bitrate * 1000)  # 以 Kbits/sec 為單位
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
    
    h264parser = Gst.ElementFactory.make("h264parse", "parser")
    if not h264parser:
        print("無法建立h264parse元素，可能需要安裝對應的GStreamer外掛")
        return None

    # RTMP串流

    flvmux = Gst.ElementFactory.make("flvmux", "flvmux")
    if not flvmux:
        print("無法建立flvmux元素，可能需要安裝對應的GStreamer外掛")
        return None

    rtmp_sink = Gst.ElementFactory.make("rtmpsink", "rtmp_sink")
    if not rtmp_sink:
        print("無法建立 rtmpsink 元素，可能需要安裝對應的GStreamer外掛")
        return None        
    rtmp_sink.set_property("location", rtmp_url)

    # 將元素加入管道
    pipeline.add(source)  # v4l2src
    pipeline.add(capsfilter1)  # capsfilter
    pipeline.add(vidconvsrc)  # videoconvert
    pipeline.add(nvvidconv)  # nvvideoconvert
    pipeline.add(encoder)  # nvv4l2h264enc
    pipeline.add(h264parser)  # h264parse

    # RTMP串流
    pipeline.add(flvmux)  # flvmux
    pipeline.add(rtmp_sink)  # rtmpsink

    # 連接元素
    source.link(capsfilter1)
    capsfilter1.link(vidconvsrc)
    vidconvsrc.link(nvvidconv)
    nvvidconv.link(encoder)
    encoder.link(h264parser)

    # RTMP串流
    h264parser.link(flvmux)
    flvmux.link(rtmp_sink)

    
    print("Complete pipeline for rtmp streaming")
    print(f"rtmp URL: {rtmp_url}")

        
    return pipeline
    


def main():
    # check arguments and switch between actions(check devices, show devices details) and main
    # check if the first argument is --list-devices
    # use argparse.ArgumentParser
    parser = argparse.ArgumentParser(description="轉換USB webcam串流到rtmp或本地顯示")
    parser.add_argument('--list-devices', action='store_true', help="列出所有可用的USB攝影機設備")
    parser.add_argument('--show-device', action='store_true', help="顯示指定設備的詳細資訊")
    parser.add_argument('--device', type=str, help="指定要使用的USB攝影機設備路徑，例如/dev/video0")
    parser.add_argument('--rtmp_url', type=str, help="指定rtmp URL")
    parser.add_argument('--rtmp', action='store_true', help="將串流轉換為rtmp")
    parser.add_argument('--width', type=int, default=640, help="影像寬度")
    parser.add_argument('--height', type=int, default=480, help="影像高度")
    parser.add_argument('--fps', type=int, default=30, help="影像幀率")
    parser.add_argument('--bitrate', type=int, default=2000, help="H264編碼比特率")

    # 如果沒有參數，顯示說明
    if len(sys.argv) == 1:
        parser.print_help()
        return

    args = parser.parse_args()
    
    if args.list_devices:
        devices = list_all_devices()
        if devices:
            print("可用的USB攝影機設備:")
            for device in devices:
                print(device)
        else:
            print("沒有找到可用的USB攝影機設備")
        return
    elif args.show_device:
        if args.device:
            print(f"顯示設備 {args.device} 的詳細資訊")
            show_device_capabilities(args.device)
        else:
            print("錯誤: 請指定要顯示的設備路徑，例如 --device /dev/video0")
            print("使用 -h 或 --help 參數查看完整說明")
        return
    
    # 檢查rtmp或本地顯示時必須指定設備
    if args.rtmp and not args.device:
        print("錯誤: 使用 --rtmp 時，必須使用 --device 參數指定設備")
        print("使用 -h 或 --help 參數查看完整說明")
        return
        
    # 若未指定任何操作模式
    if not args.rtmp:
        print("錯誤: 請指定要執行的操作 (--rtmp)")
        print("使用 -h 或 --help 參數查看完整說明")
        return
    
    if args.rtmp:
        # rtmp的實作
        pipeline = main_pipeline(args.device, args.width, args.height, args.fps, args.bitrate, rtmp_url=args.rtmp_url)
        if not pipeline:
            print("無法建立管道")
            return
        
        # 啟動管道
        pipeline.set_state(Gst.State.PLAYING)
        print("開始rtmp串流...")
        # 等待結束
        try:
            loop = GLib.MainLoop()
            loop.run()
        except KeyboardInterrupt:
            print("停止rtmp串流...")
        finally:
            pipeline.set_state(Gst.State.NULL)
            print("管道已停止")
    else:
        print("錯誤: 未知的操作模式")
        print("使用 -h 或 --help 參數查看完整說明")
        return

        
    
if __name__ == "__main__":
    main()

# python3 usb_to_rtmp2.py  --list-devices
# python3 usb_to_rtmp2.py  --show-device --device /dev/video0
# python3 usb_to_rtmp2.py  --device /dev/video0 --rtmp --rtmp_url rtmp://192.168.1.222/test1 --width 640 --height 480 --fps 5