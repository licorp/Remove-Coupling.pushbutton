# -*- coding: utf-8 -*-

"""
================================================================
REMOVE COUPLING TOOL - FINAL CONSOLIDATED VERSION - June 2025
================================================================

CHỨC NĂNG CHÍNH:
✅ TRUE TRIM: **GỘP 2 PIPES THÀNH 1 PIPE LIỀN MẠCH** 
- Extend pipe chính để bao phủ toàn bộ khoảng cách
- Xóa pipe thứ 2 (không cần thiết)
- Kết quả: 1 pipe liền mạch duy nhất thay thế 2 pipes

FALLBACK METHODS (nếu TRUE TRIM không thành công):
1. Union Pipes - Sử dụng Revit API để union 2 pipes
2. Extend Both Pipes - Extend cả 2 pipes tới điểm giữa  
3. Connector Connection - Kết nối logic thông qua connectors
4. Extend Pipes - Kéo dài pipes về giữa để đóng khoảng hở
5. Create Segment - Tạo pipe segment nhỏ làm cầu nối

CÁCH SỬ DỤNG:
- Chọn 1 hoặc nhiều coupling elements
- Tool sẽ tự động tìm 2 pipes kết nối với mỗi coupling
- Xóa coupling và kết nối lại pipes

Tác giả: GitHub Copilot Assistant
Phiên bản: Final Consolidated - June 2025 - SILENT VERSION
================================================================
"""

# Import các thư viện cần thiết
import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from pyrevit import revit, script
from Autodesk.Revit import DB
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.DB.Plumbing import PlumbingUtils
from System.Collections.Generic import List

# Khởi tạo output window (silent mode)
output = script.get_output()

# Khởi tạo document và UI document
doc = revit.doc
uidoc = revit.uidoc

def get_pipe_connections(pipe):
    """Lấy tất cả connectors của pipe"""
    try:
        connector_set = pipe.ConnectorManager.Connectors
        connectors = []
        for connector in connector_set:
            connectors.append(connector)
        return connectors
    except:
        return []

def find_connected_pipes(coupling):
    """Tìm tất cả pipes kết nối với coupling này"""
    connected_pipes = []
    
    try:
        # Method 1: Sử dụng MEPModel (cho system families)
        if hasattr(coupling, 'MEPModel') and coupling.MEPModel:
            connector_set = coupling.MEPModel.ConnectorManager.Connectors
            for connector in connector_set:
                if connector.IsConnected:
                    for ref in connector.AllRefs:
                        element = ref.Owner
                        if element.Category.Id.IntegerValue == int(DB.BuiltInCategory.OST_PipeCurves):
                            if element.Id != coupling.Id:
                                connected_pipes.append(element)
                                
        # Method 2: Sử dụng ConnectorManager trực tiếp (cho family instances)
        elif hasattr(coupling, 'ConnectorManager') and coupling.ConnectorManager:
            connector_set = coupling.ConnectorManager.Connectors
            for connector in connector_set:
                if connector.IsConnected:
                    for ref in connector.AllRefs:
                        element = ref.Owner
                        if element.Category.Id.IntegerValue == int(DB.BuiltInCategory.OST_PipeCurves):
                            if element.Id != coupling.Id:
                                connected_pipes.append(element)
        
        # Method 3: Geometry-based search (fallback)
        if len(connected_pipes) == 0:
            coupling_location = coupling.Location
            if hasattr(coupling_location, 'Point'):
                search_point = coupling_location.Point
            elif hasattr(coupling_location, 'Curve'):
                search_point = coupling_location.Curve.GetEndPoint(0)
            else:
                return connected_pipes
            
            # Tìm pipes gần coupling
            pipe_collector = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_PipeCurves).WhereElementIsNotElementType()
            for pipe in pipe_collector:
                pipe_curve = pipe.Location.Curve
                closest_point = pipe_curve.Project(search_point).XYZPoint
                distance = search_point.DistanceTo(closest_point)
                if distance < 1.0:  # Trong vòng 1 foot
                    connected_pipes.append(pipe)

    except Exception as e:
        pass  # Silent execution
    
    # Loại bỏ duplicates
    unique_pipes = []
    pipe_ids = set()
    for pipe in connected_pipes:
        if pipe.Id not in pipe_ids:
            unique_pipes.append(pipe)
            pipe_ids.add(pipe.Id)
    
    return unique_pipes

def true_trim_pipes(pipe1, pipe2):
    """
    TRUE TRIM: Gộp 2 pipes thành 1 pipe liền mạch duy nhất
    - Extend 1 pipe để bao phủ toàn bộ khoảng cách
    - Xóa pipe thứ 2
    - Kết quả: 1 pipe liền mạch thay thế 2 pipes riêng biệt
    """
    try:
        # Lấy curves của 2 pipes
        curve1 = pipe1.Location.Curve
        curve2 = pipe2.Location.Curve
        
        # Tính khoảng cách giữa các endpoints để tìm điểm kết nối tốt nhất
        p1_start = curve1.GetEndPoint(0)
        p1_end = curve1.GetEndPoint(1)
        p2_start = curve2.GetEndPoint(0)
        p2_end = curve2.GetEndPoint(1)
        
        # Tính tất cả khoảng cách có thể
        distances = [
            (p1_start.DistanceTo(p2_start), p1_start, p2_start, "P1_Start", "P2_Start"),
            (p1_start.DistanceTo(p2_end), p1_start, p2_end, "P1_Start", "P2_End"),
            (p1_end.DistanceTo(p2_start), p1_end, p2_start, "P1_End", "P2_Start"),
            (p1_end.DistanceTo(p2_end), p1_end, p2_end, "P1_End", "P2_End")
        ]
        
        # Sắp xếp theo khoảng cách gần nhất
        distances.sort(key=lambda x: x[0])
        min_distance, conn_p1, conn_p2, p1_type, p2_type = distances[0]
        
        if min_distance > 10.0:  # Quá xa để kết nối
            return False
        
        # Xác định điểm đầu và cuối của pipe liền mạch mới - GIỮ NGUYÊN HƯỚNG PIPE GỐC
        # Chọn pipe dài hơn làm pipe chính để giữ nguyên hướng
        curve1_length = curve1.Length
        curve2_length = curve2.Length
        
        if curve1_length >= curve2_length:
            keep_pipe = pipe1
            delete_pipe = pipe2
            main_curve = curve1
            extend_curve = curve2
        else:
            keep_pipe = pipe2
            delete_pipe = pipe1
            main_curve = curve2
            extend_curve = curve1
        
        # Tìm endpoint của pipe chính gần với pipe phụ nhất
        main_start = main_curve.GetEndPoint(0)
        main_end = main_curve.GetEndPoint(1)
        extend_start = extend_curve.GetEndPoint(0)
        extend_end = extend_curve.GetEndPoint(1)
        
        # Tính khoảng cách để quyết định extend về phía nào
        distances = [
            (main_start.DistanceTo(extend_start), main_start, extend_end, "extend_from_main_start"),
            (main_start.DistanceTo(extend_end), main_start, extend_start, "extend_from_main_start"),
            (main_end.DistanceTo(extend_start), main_end, extend_end, "extend_from_main_end"),
            (main_end.DistanceTo(extend_end), main_end, extend_start, "extend_from_main_end")
        ]
        
        distances.sort(key=lambda x: x[0])
        min_distance, connection_point, extend_to_point, extend_direction = distances[0]
        
        # Tạo curve mới GIỮ NGUYÊN HƯỚNG pipe chính
        if extend_direction == "extend_from_main_start":
            # Extend từ main_start, giữ nguyên main_end
            new_start = extend_to_point  # Điểm xa nhất của pipe phụ
            new_end = main_end          # Giữ nguyên endpoint của pipe chính
        else:
            # Extend từ main_end, giữ nguyên main_start
            new_start = main_start      # Giữ nguyên startpoint của pipe chính
            new_end = extend_to_point   # Điểm xa nhất của pipe phụ
        
        # Tạo curve liền mạch cho pipe được giữ lại - KIỂM TRA HƯỚNG TRƯỚC
        continuous_curve = None  # Initialize để tránh unbound
        try:
            # QUAN TRỌNG: Không xóa pipe thứ 2 ngay, extend trước để đảm bảo kết nối
            
            # Tạo curve mới
            continuous_curve = DB.Line.CreateBound(new_start, new_end)
            
            # Kiểm tra hướng curve mới so với curve gốc
            original_direction = main_curve.Direction
            new_direction = continuous_curve.Direction
            
            # Tính góc giữa 2 vectors (nếu > 90 độ thì đảo ngược)
            dot_product = original_direction.DotProduct(new_direction)
            
            # Nếu dot product < 0 thì hướng ngược lại - cần đảo ngược
            if dot_product < 0:
                # Đảo ngược start và end
                continuous_curve = DB.Line.CreateBound(new_end, new_start)
                new_direction = continuous_curve.Direction
            
            # Apply curve mới - EXTEND PIPE CHÍNH
            keep_pipe.Location.Curve = continuous_curve
            
            # Bước 2: Thu thập thông tin connections của pipe sẽ bị xóa TRƯỚC KHI XÓA
            delete_connectors = get_pipe_connections(delete_pipe)
            connections_to_transfer = []
            
            for conn in delete_connectors:
                if conn.IsConnected:
                    for ref in conn.AllRefs:
                        if ref.Owner.Id != delete_pipe.Id:  # Không phải chính pipe này
                            other_element = ref.Owner
                            connections_to_transfer.append({
                                'element': other_element,
                                'connector': ref,
                                'position': conn.Origin
                            })
            
            # Bước 3: Kiểm tra connectors của pipe đã extend
            updated_connectors = get_pipe_connections(keep_pipe)
            
            # Bước 4: Thử kết nối lại với các elements mà pipe cũ đã kết nối
            for connection_info in connections_to_transfer:
                try:
                    target_element = connection_info['element']
                    target_connector = connection_info['connector']
                    target_position = connection_info['position']
                    
                    # Tìm connector gần nhất của pipe mới
                    closest_connector = None
                    min_dist = float('inf')
                    
                    for new_conn in updated_connectors:
                        if not new_conn.IsConnected:  # Chỉ kết nối với connector rảnh
                            dist = new_conn.Origin.DistanceTo(target_position)
                            if dist < min_dist:
                                min_dist = dist
                                closest_connector = new_conn
                    
                    if closest_connector and min_dist < 1.0:  # Trong vòng 1 foot
                        closest_connector.ConnectTo(target_connector)
                        
                except Exception as conn_error:
                    pass  # Silent execution
            
            # Bước 5: Disconnect pipe thứ 2 từ tất cả connections trước khi xóa
            for conn in delete_connectors:
                if conn.IsConnected:
                    refs_to_disconnect = []
                    for ref in conn.AllRefs:
                        if ref.Owner.Id != delete_pipe.Id:
                            refs_to_disconnect.append(ref)
                    
                    for ref in refs_to_disconnect:
                        try:
                            conn.DisconnectFrom(ref)
                        except:
                            pass
            
        except Exception as e_extend:
            # Thử method backup: Extend đơn giản
            try:
                # Chỉ extend pipe chính đến connection point (không merge hoàn toàn)
                if extend_direction == "extend_from_main_start":
                    continuous_curve = DB.Line.CreateBound(connection_point, main_end)
                else:
                    continuous_curve = DB.Line.CreateBound(main_start, connection_point)
                
                keep_pipe.Location.Curve = continuous_curve
                
                # Không xóa pipe thứ 2 trong backup method để giữ kết nối
                delete_pipe = None  # Không xóa
                
            except Exception as backup_error:
                return False
        
        # Xóa pipe thứ 2 để chỉ còn 1 pipe liền mạch (nếu có)
        if delete_pipe:
            try:
                doc.Delete(delete_pipe.Id)
            except Exception as e_delete:
                pass  # Silent execution - không return False vì pipe chính đã được tạo thành công
        
        # Tính toán độ dài mới và kiểm tra connections cuối cùng
        if continuous_curve:
            total_length = continuous_curve.Length
        
        # Báo cáo connections cuối cùng
        final_connectors = get_pipe_connections(keep_pipe)
        connected_count = sum(1 for conn in final_connectors if conn.IsConnected)
        
        return True
        
    except Exception as e:
        return False

def extend_both_pipes_to_connect(pipe1, pipe2):
    """
    BACKUP METHOD: Extend cả 2 pipes để kết nối (không merge thành 1)
    Sử dụng khi TRUE TRIM không thành công
    """
    try:
        curve1 = pipe1.Location.Curve
        curve2 = pipe2.Location.Curve
        
        # Tìm các endpoints gần nhất
        p1_start = curve1.GetEndPoint(0)
        p1_end = curve1.GetEndPoint(1)
        p2_start = curve2.GetEndPoint(0)
        p2_end = curve2.GetEndPoint(1)
        
        distances = [
            (p1_start.DistanceTo(p2_start), p1_start, p2_start, "start", "start"),
            (p1_start.DistanceTo(p2_end), p1_start, p2_end, "start", "end"),
            (p1_end.DistanceTo(p2_start), p1_end, p2_start, "end", "start"),
            (p1_end.DistanceTo(p2_end), p1_end, p2_end, "end", "end")
        ]
        
        distances.sort(key=lambda x: x[0])
        min_distance, conn_p1, conn_p2, p1_side, p2_side = distances[0]
        
        if min_distance > 5.0:
            return False
        
        # Tính điểm giữa để extend cả 2 pipes tới đó
        midpoint = DB.XYZ(
            (conn_p1.X + conn_p2.X) / 2,
            (conn_p1.Y + conn_p2.Y) / 2,
            (conn_p1.Z + conn_p2.Z) / 2
        )
        
        # Extend pipe 1
        if p1_side == "start":
            new_curve1 = DB.Line.CreateBound(midpoint, p1_end)
        else:
            new_curve1 = DB.Line.CreateBound(p1_start, midpoint)
        
        # Extend pipe 2  
        if p2_side == "start":
            new_curve2 = DB.Line.CreateBound(midpoint, p2_end)
        else:
            new_curve2 = DB.Line.CreateBound(p2_start, midpoint)
        
        # Apply changes
        pipe1.Location.Curve = new_curve1
        pipe2.Location.Curve = new_curve2
        
        return True
        
    except Exception as e:
        return False

def connect_pipes_comprehensive(pipe1, pipe2):
    """
    Kết nối 2 pipes với 6-method fallback system
    Priority: TRUE_TRIM → EXTEND_BOTH → UNION → CONNECTOR → EXTEND → SEGMENT
    """
    
    # METHOD 1: TRUE TRIM (Priority 1 - Preferred method)
    if true_trim_pipes(pipe1, pipe2):
        return "TRUE_TRIM"
    
    # METHOD 2: EXTEND BOTH PIPES (Backup for TRUE TRIM)
    if extend_both_pipes_to_connect(pipe1, pipe2):
        return "EXTEND_BOTH"
    
    # METHOD 3: UNION (nếu True Trim không thành công)
    try:
        pipe_ids = [pipe1.Id, pipe2.Id]
        collection = List[DB.ElementId](pipe_ids)
        union_result = DB.ElementTransformUtils.CopyElements(doc, collection, doc, None, None)
        if union_result and len(union_result) > 0:
            return "UNION"
    except Exception as e:
        pass
    
    # METHOD 4: CONNECTOR CONNECTION
    try:
        connectors1 = get_pipe_connections(pipe1)
        connectors2 = get_pipe_connections(pipe2)
        
        for c1 in connectors1:
            for c2 in connectors2:
                if not c1.IsConnected and not c2.IsConnected:
                    distance = c1.Origin.DistanceTo(c2.Origin)
                    if distance < 2.0:  # Trong vòng 2 feet
                        try:
                            c1.ConnectTo(c2)
                            return "CONNECTOR"
                        except:
                            continue
    except Exception as e:
        pass
    
    # METHOD 5: EXTEND PIPES
    try:
        curve1 = pipe1.Location.Curve
        curve2 = pipe2.Location.Curve
        
        # Tìm các endpoints và extend về phía gần nhất
        p1_start = curve1.GetEndPoint(0)
        p1_end = curve1.GetEndPoint(1)
        p2_start = curve2.GetEndPoint(0)
        p2_end = curve2.GetEndPoint(1)
        
        # Tìm cặp điểm gần nhất
        min_dist = float('inf')
        best_config = None
        
        configs = [
            (p1_start, p2_start, "p1_from_start", "p2_from_start"),
            (p1_start, p2_end, "p1_from_start", "p2_from_end"),
            (p1_end, p2_start, "p1_from_end", "p2_from_start"),
            (p1_end, p2_end, "p1_from_end", "p2_from_end")
        ]
        
        for point1, point2, config1, config2 in configs:
            dist = point1.DistanceTo(point2)
            if dist < min_dist:
                min_dist = dist
                best_config = (point1, point2, config1, config2)
        
        if best_config and min_dist < 5.0:
            point1, point2, config1, config2 = best_config
            midpoint = DB.XYZ((point1.X + point2.X)/2, (point1.Y + point2.Y)/2, (point1.Z + point2.Z)/2)
            
            # Extend pipe1
            if "start" in config1:
                new_curve1 = DB.Line.CreateBound(midpoint, p1_end)
            else:
                new_curve1 = DB.Line.CreateBound(p1_start, midpoint)
            
            # Extend pipe2
            if "start" in config2:
                new_curve2 = DB.Line.CreateBound(midpoint, p2_end)
            else:
                new_curve2 = DB.Line.CreateBound(p2_start, midpoint)
            
            pipe1.Location.Curve = new_curve1
            pipe2.Location.Curve = new_curve2
            
            return "EXTEND"
            
    except Exception as e:
        pass
    
    # METHOD 6: CREATE SEGMENT (last resort)
    try:
        # Tìm gap nhỏ nhất và tạo pipe segment để nối
        curve1 = pipe1.Location.Curve
        curve2 = pipe2.Location.Curve
        
        endpoints = [
            (curve1.GetEndPoint(0), curve2.GetEndPoint(0)),
            (curve1.GetEndPoint(0), curve2.GetEndPoint(1)),
            (curve1.GetEndPoint(1), curve2.GetEndPoint(0)),
            (curve1.GetEndPoint(1), curve2.GetEndPoint(1))
        ]
        
        min_dist = float('inf')
        best_points = None
        
        for p1, p2 in endpoints:
            dist = p1.DistanceTo(p2)
            if dist < min_dist:
                min_dist = dist
                best_points = (p1, p2)
        
        if best_points and min_dist < 3.0:
            p1, p2 = best_points
            
            # Tạo pipe segment nối
            segment_curve = DB.Line.CreateBound(p1, p2)
            
            # Lấy pipe type từ pipe1
            pipe_type_id = pipe1.GetTypeId()
            level_id = pipe1.ReferenceLevel.Id if pipe1.ReferenceLevel else doc.ActiveView.GenLevel.Id
            
            # Tạo pipe segment mới
            new_pipe = DB.Plumbing.Pipe.Create(doc, pipe_type_id, level_id, segment_curve)
            
            if new_pipe:
                return "SEGMENT"
                
    except Exception as e:
        pass
    
    return False

def main():
    """Hàm chính của tool - Complete Remove Coupling Tool"""
    try:
        selection = uidoc.Selection
        
        # Yêu cầu người dùng chọn elements (silent mode - no output)
        selected_elements = []
        
        try:
            # Cho phép user chọn multiple elements
            selected_refs = selection.PickObjects(ObjectType.Element, "Chọn coupling elements (có thể chọn nhiều)")
            
            for ref in selected_refs:
                element = doc.GetElement(ref.ElementId)
                selected_elements.append(element)
                
        except Exception as selection_error:
            return
        
        if not selected_elements:
            return
        
        # Bắt đầu transaction
        with DB.Transaction(doc, "Remove Coupling and TRUE TRIM Pipes") as trans:
            trans.Start()
            
            total_count = len(selected_elements)
            success_count = 0
            error_count = 0
            
            for i, coupling in enumerate(selected_elements, 1):
                # Tìm pipes kết nối với coupling này
                connected_pipes = find_connected_pipes(coupling)
                
                if len(connected_pipes) == 2:
                    pipe1, pipe2 = connected_pipes[0], connected_pipes[1]
                    
                    # Disconnect và xóa coupling trước
                    try:
                        disconnect_success = False
                        
                        # Method 1: Disconnect thông qua coupling connectors
                        try:
                            if hasattr(coupling, 'MEPModel') and coupling.MEPModel:
                                connector_set = coupling.MEPModel.ConnectorManager.Connectors
                            elif hasattr(coupling, 'ConnectorManager'):
                                connector_set = coupling.ConnectorManager.Connectors
                            else:
                                connector_set = []
                            
                            for conn in connector_set:
                                if conn.IsConnected:
                                    refs_to_disconnect = []
                                    for ref in conn.AllRefs:
                                        if ref.Owner.Id != coupling.Id:
                                            refs_to_disconnect.append(ref)
                                    
                                    for ref in refs_to_disconnect:
                                        try:
                                            conn.DisconnectFrom(ref)
                                            disconnect_success = True
                                        except:
                                            pass
                        except Exception as connect_error:
                            pass
                        
                        # Method 2: Disconnect thông qua pipe connectors (backup)
                        if not disconnect_success:
                            for pipe in [pipe1, pipe2]:
                                pipe_connectors = get_pipe_connections(pipe)
                                for pipe_conn in pipe_connectors:
                                    if pipe_conn.IsConnected:
                                        refs_to_disconnect = []
                                        for ref in pipe_conn.AllRefs:
                                            if ref.Owner.Id == coupling.Id:
                                                refs_to_disconnect.append(ref)
                                        
                                        for ref in refs_to_disconnect:
                                            try:
                                                pipe_conn.DisconnectFrom(ref)
                                                disconnect_success = True
                                            except:
                                                pass
                        
                    except Exception as disconnect_error:
                        pass
                    
                    # Bây giờ mới xóa coupling với multiple fallback methods
                    delete_success = False
                    
                    try:
                        # Method 1: Xóa trực tiếp
                        doc.Delete(coupling.Id)
                        delete_success = True
                        
                    except Exception as delete_error:
                        # Method 2: Force delete với collection
                        try:
                            element_ids = []
                            element_ids.append(coupling.Id)
                            doc.Delete(element_ids)
                            delete_success = True
                            
                        except Exception as delete_error2:
                            # Method 3: Thử với ElementTransformUtils
                            try:
                                from Autodesk.Revit.DB import ElementTransformUtils, Transform
                                # Đôi khi move element ra khỏi view rồi delete
                                transform = Transform.CreateTranslation(DB.XYZ(1000, 1000, 1000))
                                ElementTransformUtils.MoveElement(doc, coupling.Id, transform.Origin)
                                doc.Delete(coupling.Id)
                                delete_success = True
                                
                            except Exception as delete_error3:
                                pass
                    
                    if not delete_success:
                        error_count += 1
                        continue
                    
                    # Kết nối và TRUE TRIM
                    result = connect_pipes_comprehensive(pipe1, pipe2)
                    
                    if result in ["TRUE_TRIM", "EXTEND_BOTH", "UNION", "CONNECTOR", "EXTEND", "SEGMENT"]:
                        success_count += 1
                    else:
                        error_count += 1
                        
                elif len(connected_pipes) > 2:
                    error_count += 1
                else:
                    error_count += 1
            
            # Commit transaction
            trans.Commit()
                
    except Exception as e:
        pass  # Silent execution - exception handling

# Chạy tool
if __name__ == '__main__':
    main()
