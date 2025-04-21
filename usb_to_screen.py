#!/usr/bin/env python3  # 指定使用Python3執行腳本
# 檔名: usb_to_rtsp.py  # 檔案名稱說明
# 功能: 將USB網路攝影機影像串流轉成H264播放  # 檔案功能說明

import argparse  # 導入命令行參數處理模組
import sys  # 導入系統模組
import gi  # 導入GObject Introspection模組
gi.require_version('Gst', '1.0')  # 指定使用GStreamer 1.0版本
from gi.repository import Gst  # 從gi.repository導入GStreamer
import subprocess  # 導入子進程模組用於執行系統命令
import re  # 導入正則表達式模組

def list_all_devices():  # 定義列出所有可用USB攝影機設備的函數
    """列出所有可用的USB攝影機設備，使用v4l2-ctl查詢"""  # 函數說明文檔
    
    try:  # 嘗試執行以下代碼
        # 執行v4l2-ctl --list-devices命令
        result = subprocess.run(['v4l2-ctl', '--list-devices'],  # 執行v4l2-ctl命令列出設備
                               stdout=subprocess.PIPE,  # 捕獲標準輸出
                               stderr=subprocess.PIPE,  # 捕獲標準錯誤
                               text=True)  # 以文本形式返回結果
        
        if result.returncode != 0:  # 如果命令執行失敗
            print(f"v4l2-ctl命令執行失敗: {result.stderr}")  # 打印錯誤信息
            return []  # 返回空列表
        
        # 使用正則表達式找出所有/dev/video開頭的設備路徑
        devices = re.findall(r'/dev/video\d+', result.stdout)  # 用正則表達式匹配設備路徑
        return devices  # 返回找到的設備列表
    
    except FileNotFoundError:  # 如果找不到v4l2-ctl工具
        print("找不到v4l2-ctl工具，請先安裝v4l-utils套件")  # 提示安裝必要工具
        return []  # 返回空列表
    except Exception as e:  # 捕獲其他所有異常
        print(f"查詢設備時出錯: {e}")  # 打印錯誤信息
        return []  # 返回空列表

def show_device_capabilities(device):  # 定義顯示設備詳細信息的函數
    """顯示指定設備的詳細資訊"""  # 函數說明文檔
    try:  # 嘗試執行以下代碼
        # 執行v4l2-ctl --list-formats-ext命令來獲取設備支援的格式資訊
        result = subprocess.run(['v4l2-ctl', '--device', device, '--list-formats-ext'],  # 執行命令獲取設備支持的格式
                               stdout=subprocess.PIPE,  # 捕獲標準輸出
                               stderr=subprocess.PIPE,  # 捕獲標準錯誤
                               text=True)  # 以文本形式返回結果
        
        if result.returncode != 0:  # 如果命令執行失敗
            print(f"無法獲取設備 {device} 的資訊: {result.stderr}")  # 打印錯誤信息
            return  # 結束函數
        
        # 顯示結果
        print(result.stdout)  # 打印設備支持的格式信息
    except FileNotFoundError:  # 如果找不到v4l2-ctl工具
        print("找不到v4l2-ctl工具，請先安裝v4l-utils套件")  # 提示安裝必要工具
    except Exception as e:  # 捕獲其他所有異常
        print(f"查詢設備資訊時出錯: {e}")  # 打印錯誤信息

def main_pipeline(device, width, height, fps, bitrate, rtsp_url=None):  # 定義創建GStreamer管道的主函數
    """建立GStreamer管道"""  # 函數說明文檔
    # 初始化GStreamer
    Gst.init(None)  # 初始化GStreamer庫
        
    # 建立GStreamer管道
    pipeline = Gst.Pipeline()  # 創建一個GStreamer管道對象

    # 建立元素
    source = Gst.ElementFactory.make("v4l2src", "source")  # 創建視頻捕獲源元素
    if not source:  # 如果創建失敗
        print("無法建立source元素，可能需要安裝對應的GStreamer外掛")  # 提示需要安裝插件
        return None  # 返回None表示失敗
    source.set_property("device", device)  # 設置攝像頭設備路徑
    print(f"使用設備: {device}")  # 打印使用的設備信息
    
    # 設定格式為YUY2
    capsfilter1 = Gst.ElementFactory.make("capsfilter", "capsfilter1")  # 創建格式過濾器元素
    if not capsfilter1:  # 如果創建失敗
        print("無法建立capsfilter元素，可能需要安裝對應的GStreamer外掛")  # 提示需要安裝插件
        return None  # 返回None表示失敗
    caps1 = Gst.Caps.from_string(f"video/x-raw,width={width},height={height},framerate={fps}/1")  # 創建視頻格式描述
    
    capsfilter1.set_property("caps", caps1)  # 設置格式過濾器屬性
    print(f"設定影像格式: {width}x{height}, {fps}fps")  # 打印設置的視頻格式信息

    vidconvsrc = Gst.ElementFactory.make("videoconvert", "convertor_src1")  # 創建視頻格式轉換元素
    if not vidconvsrc:  # 如果創建失敗
        sys.stderr.write(" Unable to create videoconvert \n")  # 輸出錯誤信息

    
    # NVIDIA影像轉換器
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "nvvidconv")  # 創建NVIDIA視頻格式轉換元素
    if not nvvidconv:  # 如果創建失敗
        print("無法建立nvvidconv元素，可能需要安裝對應的GStreamer外掛")  # 提示需要安裝插件
        return None  # 返回None表示失敗
    
    # 嘗試使用NVIDIA硬體H264編碼器 (優先順序)
    # 1. nvv4l2h264enc - NVIDIA V4L2 based hardware encoder for Jetson
    # 2. nvh264enc - NVIDIA GPU based encoder for dGPU platforms
    # 3. x264enc - Software encoder as fallback
    encoder = Gst.ElementFactory.make("nvv4l2h264enc", "encoder")  # 嘗試創建NVIDIA V4L2 H264編碼器
    if not encoder:  # 如果創建失敗
        print("無法建立nvv4l2h264enc元素，嘗試使用nvh264enc...")  # 提示嘗試使用替代編碼器
        encoder = Gst.ElementFactory.make("nvh264enc", "encoder")  # 嘗試創建NVIDIA GPU H264編碼器
        if not encoder:  # 如果創建失敗
            print("無法建立nvh264enc元素，嘗試使用x264enc...")  # 提示嘗試使用軟件編碼器
            encoder = Gst.ElementFactory.make("x264enc", "encoder")  # 嘗試創建軟件H264編碼器
            if not encoder:  # 如果創建失敗
                print("無法建立任何H264編碼器，請安裝所需的GStreamer外掛")  # 提示需要安裝插件
                return None  # 返回None表示失敗
    
    # 設定編碼器參數 (根據不同編碼器調整參數)
    if encoder.get_factory().get_name() == "nvv4l2h264enc":  # 如果是NVIDIA V4L2編碼器
        # nvv4l2h264enc 參數設定 (用於 Jetson)
        encoder.set_property("bitrate", bitrate * 1000)  # 設置比特率，單位為比特/秒
    elif encoder.get_factory().get_name() == "nvh264enc":  # 如果是NVIDIA GPU編碼器
        # nvh264enc 參數設定 (用於 dGPU)
        encoder.set_property("bitrate", bitrate)  # 設置比特率，單位為千比特/秒
        encoder.set_property("preset", 1)  # 設置預設值：0=慢，1=中，2=快
        encoder.set_property("rc-mode", 1)  # 設置碼率控制模式：1=固定碼率，2=可變碼率
    else:  # 如果是軟件編碼器
        # x264enc 參數設定 (軟體編碼)
        encoder.set_property("bitrate", bitrate)  # 設置比特率
        encoder.set_property("speed-preset", "medium")  # 設置速度預設為中等
        encoder.set_property("tune", "zerolatency")  # 設置優化為零延遲模式


    print(f"使用 {encoder.get_factory().get_name()} 編碼器")  # 打印使用的編碼器名稱

    decodebin = Gst.ElementFactory.make("decodebin", "decoder")  # 創建解碼器元素
    if not decodebin:  # 如果創建失敗
        print("無法建立decodebin元素，可能需要安裝對應的GStreamer外掛")  # 提示需要安裝插件
        return None  # 返回None表示失敗
    
    videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")  # 創建視頻格式轉換元素
    if not videoconvert:  # 如果創建失敗
        print("無法建立videoconvert元素，可能需要安裝對應的GStreamer外掛")  # 提示需要安裝插件
        return None  # 返回None表示失敗
    
    sink = Gst.ElementFactory.make("autovideosink", "sink")  # 創建自動視頻輸出元素
    if not sink:  # 如果創建失敗
        print("無法建立autovideosink元素，可能需要安裝對應的GStreamer外掛")  # 提示需要安裝插件
        return None  # 返回None表示失敗
    
    # 將元素加入管道
    pipeline.add(source)  # 添加視頻源元素到管道
    pipeline.add(capsfilter1)  # 添加格式過濾器到管道
    pipeline.add(vidconvsrc)  # 添加視頻格式轉換器到管道
    pipeline.add(nvvidconv)  # 添加NVIDIA視頻格式轉換器到管道
    pipeline.add(encoder)  # 添加編碼器到管道
    pipeline.add(decodebin)  # 添加解碼器到管道
    pipeline.add(videoconvert)  # 添加視頻格式轉換器到管道
    pipeline.add(sink)  # 添加視頻輸出元素到管道
    
    # 連接元素
    source.link(capsfilter1)  # 連接視頻源到格式過濾器
    capsfilter1.link(vidconvsrc)  # 連接格式過濾器到視頻格式轉換器
    vidconvsrc.link(nvvidconv)  # 連接視頻格式轉換器到NVIDIA視頻格式轉換器
    nvvidconv.link(encoder)  # 連接NVIDIA視頻格式轉換器到編碼器
    encoder.link(decodebin)  # 連接編碼器到解碼器
    
    # 處理動態連接
    decodebin.connect("pad-added", lambda dbin, pad: pad.link(videoconvert.get_static_pad("sink")))  # 當解碼器產生新的pad時，連接到視頻轉換器
    videoconvert.link(sink)  # 連接視頻格式轉換器到視頻輸出

    print("Complete pipeline for local display")  # 打印管道設置完成信息

    return pipeline  # 返回創建的管道對象
    


def main():  # 定義主函數
    # check arguments and switch between actions(check devices, show devices details) and main
    # check if the first argument is --list-devices
    # use argparse.ArgumentParser
    parser = argparse.ArgumentParser(description="轉換USB webcam串流到RTSP或本地顯示")  # 創建命令行參數解析器
    parser.add_argument('--list-devices', action='store_true', help="列出所有可用的USB攝影機設備")  # 添加列出設備參數
    parser.add_argument('--show-device', action='store_true', help="顯示指定設備的詳細資訊")  # 添加顯示設備詳情參數
    parser.add_argument('--device', type=str, help="指定要使用的USB攝影機設備路徑，例如/dev/video0")  # 添加設備路徑參數
    parser.add_argument('--local', action='store_true', help="將串流顯示在本地")  # 添加本地顯示參數
    parser.add_argument('--width', type=int, default=640, help="影像寬度")  # 添加影像寬度參數
    parser.add_argument('--height', type=int, default=480, help="影像高度")  # 添加影像高度參數
    parser.add_argument('--fps', type=int, default=30, help="影像幀率")  # 添加影像幀率參數
    parser.add_argument('--bitrate', type=int, default=2000, help="H264編碼比特率")  # 添加比特率參數

    # 如果沒有參數，顯示說明
    if len(sys.argv) == 1:  # 如果命令行參數只有程式名稱
        parser.print_help()  # 打印幫助信息
        return  # 結束程式

    args = parser.parse_args()  # 解析命令行參數
    
    if args.list_devices:  # 如果是列出設備模式
        devices = list_all_devices()  # 獲取所有設備列表
        if devices:  # 如果有設備
            print("可用的USB攝影機設備:")  # 打印提示
            for device in devices:  # 遍歷每個設備
                print(device)  # 打印設備路徑
        else:  # 如果沒有設備
            print("沒有找到可用的USB攝影機設備")  # 打印提示
        return  # 結束程式
    elif args.show_device:  # 如果是顯示設備詳情模式
        if args.device:  # 如果指定了設備
            print(f"顯示設備 {args.device} 的詳細資訊")  # 打印提示
            show_device_capabilities(args.device)  # 顯示設備詳情
        else:  # 如果沒有指定設備
            print("錯誤: 請指定要顯示的設備路徑，例如 --device /dev/video0")  # 打印錯誤提示
            print("使用 -h 或 --help 參數查看完整說明")  # 提示查看幫助
        return  # 結束程式
    
    # 檢查RTSP或本地顯示時必須指定設備
    if args.local and not args.device:  # 如果是本地顯示但沒有指定設備
        print("錯誤: 使用 --local 時，必須使用 --device 參數指定設備")  # 打印錯誤提示
        print("使用 -h 或 --help 參數查看完整說明")  # 提示查看幫助
        return  # 結束程式
        
    # 若未指定任何操作模式
    if not args.local:  # 如果沒有指定本地顯示
        print("錯誤: 請指定要執行的操作 (--local)")  # 打印錯誤提示
        print("使用 -h 或 --help 參數查看完整說明")  # 提示查看幫助
        return  # 結束程式
    
    pipeline = main_pipeline(args.device, args.width, args.height, args.fps, args.bitrate)  # 創建並設置GStreamer管道
    if not pipeline:  # 如果管道創建失敗
        print("無法建立管道")  # 打印錯誤提示
        return  # 結束程式
    # 啟動管道
    pipeline.set_state(Gst.State.PLAYING)  # 設置管道狀態為播放
    print("開始本地顯示...")  # 打印開始顯示的提示

    
if __name__ == "__main__":  # 如果此腳本是直接運行的
    main()  # 執行主函數

# python3 usb_to_rtsp2.py  --list-devices  # 列出所有可用的USB攝影機設備的命令示例
# python3 usb_to_rtsp2.py  --show-device --device /dev/video0  # 顯示指定設備詳情的命令示例
# python3 usb_to_rtsp2.py  --device /dev/video0 --local --width 640 --height 480 --fps 5  # 本地顯示指定設備的命令示例
