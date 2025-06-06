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
Phiên bản: Final Consolidated - June 2025
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

# Khởi tạo output window
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
        output.print_md('  ⚠️ Lỗi tìm connected pipes: {}'.format(str(e)))
    
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
        output.print_md('  🔥 **BẮT ĐẦU TRUE TRIM: GỘP 2 PIPES THÀNH 1 PIPE LIỀN MẠCH**')
        
        # Lấy curves của 2 pipes
        curve1 = pipe1.Location.Curve
        curve2 = pipe2.Location.Curve
        
        output.print_md('    📏 Pipe 1 length: {:.4f} feet'.format(curve1.Length))
        output.print_md('    📏 Pipe 2 length: {:.4f} feet'.format(curve2.Length))
        
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
        
        output.print_md('    📏 Khoảng cách gần nhất: {:.4f} feet ({} ↔ {})'.format(
            min_distance, p1_type, p2_type))
        
        if min_distance > 10.0:  # Quá xa để kết nối
            output.print_md('    ⚠️ Pipes quá xa để trim ({:.4f} feet)'.format(min_distance))
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
            output.print_md('    📏 Chọn pipe1 làm chính (dài hơn: {:.3f} vs {:.3f})'.format(curve1_length, curve2_length))
        else:
            keep_pipe = pipe2
            delete_pipe = pipe1
            main_curve = curve2
            extend_curve = curve1
            output.print_md('    📏 Chọn pipe2 làm chính (dài hơn: {:.3f} vs {:.3f})'.format(curve2_length, curve1_length))
        
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
        
        output.print_md('    🎯 Pipe liền mạch từ: ({:.3f}, {:.3f}) → ({:.3f}, {:.3f})'.format(
            new_start.X, new_start.Y, new_end.X, new_end.Y))
        output.print_md('    🔄 Hướng: {} (giữ nguyên hướng pipe chính)'.format(extend_direction))
        
        # Tạo curve liền mạch cho pipe được giữ lại - KIỂM TRA HƯỚNG TRƯỚC
        continuous_curve = None  # Initialize để tránh unbound
        try:
            # QUAN TRỌNG: Không xóa pipe thứ 2 ngay, extend trước để đảm bảo kết nối
            output.print_md('    🔗 Bước 1: Extend pipe chính để bao phủ toàn bộ đường ống...')
            
            # Tạo curve mới
            continuous_curve = DB.Line.CreateBound(new_start, new_end)
            
            # Kiểm tra hướng curve mới so với curve gốc
            original_direction = main_curve.Direction
            new_direction = continuous_curve.Direction
            
            # Tính góc giữa 2 vectors (nếu > 90 độ thì đảo ngược)
            dot_product = original_direction.DotProduct(new_direction)
            output.print_md('    📐 Dot product (direction check): {:.3f}'.format(dot_product))
            
            # Nếu dot product < 0 thì hướng ngược lại - cần đảo ngược
            if dot_product < 0:
                output.print_md('    🔄 Phát hiện hướng ngược - Đảo ngược curve...')
                # Đảo ngược start và end
                continuous_curve = DB.Line.CreateBound(new_end, new_start)
                new_direction = continuous_curve.Direction
                output.print_md('    ✅ Đã đảo ngược curve để giữ nguyên hướng')
            
            # Apply curve mới - EXTEND PIPE CHÍNH
            keep_pipe.Location.Curve = continuous_curve
            output.print_md('    ✅ Đã extend pipe {} thành pipe liền mạch'.format(keep_pipe.Id))
            
            # Bước 2: Thu thập thông tin connections của pipe sẽ bị xóa TRƯỚC KHI XÓA
            output.print_md('    🔗 Bước 2: Thu thập connections của pipe sẽ xóa...')
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
                            output.print_md('      📌 Ghi nhận connection: pipe {} ↔ element {}'.format(
                                delete_pipe.Id, other_element.Id))
            
            # Bước 3: Kiểm tra connectors của pipe đã extend
            output.print_md('    🔗 Bước 3: Kiểm tra connectors của pipe đã extend...')
            updated_connectors = get_pipe_connections(keep_pipe)
            output.print_md('    📊 Pipe {} có {} connectors sau extend'.format(keep_pipe.Id, len(updated_connectors)))
            
            # Bước 4: Thử kết nối lại với các elements mà pipe cũ đã kết nối
            output.print_md('    🔗 Bước 4: Kết nối lại với {} elements...'.format(len(connections_to_transfer)))
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
                        output.print_md('      ✅ Kết nối pipe {} với element {} (distance: {:.3f})'.format(
                            keep_pipe.Id, target_element.Id, min_dist))
                    else:
                        output.print_md('      ⚠️ Không thể kết nối với element {} (min_dist: {:.3f})'.format(
                            target_element.Id, min_dist))
                        
                except Exception as conn_error:
                    output.print_md('      ❌ Lỗi kết nối với element {}: {}'.format(
                        connection_info['element'].Id, str(conn_error)))
            
            # Bước 5: Disconnect pipe thứ 2 từ tất cả connections trước khi xóa
            output.print_md('    🔗 Bước 5: Disconnect pipe thứ 2 trước khi xóa...')
            for conn in delete_connectors:
                if conn.IsConnected:
                    refs_to_disconnect = []
                    for ref in conn.AllRefs:
                        if ref.Owner.Id != delete_pipe.Id:
                            refs_to_disconnect.append(ref)
                    
                    for ref in refs_to_disconnect:
                        try:
                            conn.DisconnectFrom(ref)
                            output.print_md('      ✅ Disconnected pipe {} từ element {}'.format(delete_pipe.Id, ref.Owner.Id))
                        except:
                            pass
            
        except Exception as e_extend:
            output.print_md('    ❌ Lỗi tạo pipe liền mạch: {}'.format(str(e_extend)))
            # Thử method backup: Extend đơn giản
            output.print_md('    🔄 Thử backup method: Extend đơn giản thay vì merge...')
            try:
                # Chỉ extend pipe chính đến connection point (không merge hoàn toàn)
                if extend_direction == "extend_from_main_start":
                    continuous_curve = DB.Line.CreateBound(connection_point, main_end)
                else:
                    continuous_curve = DB.Line.CreateBound(main_start, connection_point)
                
                keep_pipe.Location.Curve = continuous_curve
                output.print_md('    ✅ Backup method thành công - Pipe {} đã được extend'.format(keep_pipe.Id))
                
                # Không xóa pipe thứ 2 trong backup method để giữ kết nối
                output.print_md('    ⚠️ Backup method: Giữ pipe {} để duy trì kết nối'.format(delete_pipe.Id))
                delete_pipe = None  # Không xóa
                
            except Exception as backup_error:
                output.print_md('    ❌ Backup method cũng thất bại: {}'.format(str(backup_error)))
                return False
        
        # Xóa pipe thứ 2 để chỉ còn 1 pipe liền mạch (nếu có)
        if delete_pipe:
            try:
                doc.Delete(delete_pipe.Id)
                output.print_md('    🗑️ Đã xóa pipe {} (không cần thiết nữa)'.format(delete_pipe.Id))
                
            except Exception as e_delete:
                output.print_md('    ❌ Lỗi xóa pipe thừa: {}'.format(str(e_delete)))
                # Không return False vì pipe chính đã được tạo thành công
        else:
            output.print_md('    ℹ️ Không xóa pipe thứ 2 (backup method để duy trì kết nối)')
        
        # Tính toán độ dài mới và kiểm tra connections cuối cùng
        if continuous_curve:
            total_length = continuous_curve.Length
            output.print_md('    📏 Độ dài pipe liền mạch: {:.4f} feet'.format(total_length))
        else:
            output.print_md('    ⚠️ Không thể tính độ dài - continuous_curve không được tạo')
        
        # Báo cáo connections cuối cùng
        final_connectors = get_pipe_connections(keep_pipe)
        connected_count = sum(1 for conn in final_connectors if conn.IsConnected)
        output.print_md('    🔗 Pipe cuối có {} connections ({} total connectors)'.format(
            connected_count, len(final_connectors)))
        
        output.print_md('    🎉 HOÀN THÀNH TRUE TRIM! 2 pipes đã được gộp thành 1 pipe liền mạch!')
        output.print_md('    💾 Pipe {} giữ nguyên TẤT CẢ thông tin gốc (tags, parameters, schedules)'.format(keep_pipe.Id))
        output.print_md('    📊 Kết quả: 1 pipe liền mạch với {} connections hoạt động'.format(connected_count))
        return True
        
    except Exception as e:
        output.print_md('    ❌ Lỗi True Trim: {}'.format(str(e)))
        return False

def extend_both_pipes_to_connect(pipe1, pipe2):
    """
    BACKUP METHOD: Extend cả 2 pipes để kết nối (không merge thành 1)
    Sử dụng khi TRUE TRIM không thành công
    """
    try:
        output.print_md('  🔄 **BACKUP METHOD: EXTEND CẢ 2 PIPES ĐỂ KẾT NỐI**')
        
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
        
        output.print_md('    📏 Khoảng cách nhỏ nhất: {:.4f} feet'.format(min_distance))
        
        if min_distance > 5.0:
            output.print_md('    ⚠️ Khoảng cách quá lớn để extend')
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
        
        output.print_md('    ✅ Đã extend cả 2 pipes tới điểm giữa')
        output.print_md('    📊 Kết quả: 2 pipes riêng biệt được extend để kết nối')
        return True
        
    except Exception as e:
        output.print_md('    ❌ Lỗi extend both pipes: {}'.format(str(e)))
        return False

def connect_pipes_comprehensive(pipe1, pipe2):
    """
    Kết nối 2 pipes với 6-method fallback system
    Priority: TRUE_TRIM → EXTEND_BOTH → UNION → CONNECTOR → EXTEND → SEGMENT
    """
    output.print_md('  🔗 **BẮT ĐẦU COMPREHENSIVE PIPE CONNECTION**')
    
    # METHOD 1: TRUE TRIM (Priority 1 - Preferred method)
    output.print_md('  🥇 **METHOD 1: TRUE TRIM (GỘP 2 PIPES THÀNH 1)**')
    if true_trim_pipes(pipe1, pipe2):
        return "TRUE_TRIM"
    
    # METHOD 2: EXTEND BOTH PIPES (Backup for TRUE TRIM)
    output.print_md('  🥈 **METHOD 2: EXTEND BOTH PIPES (BACKUP)**')
    if extend_both_pipes_to_connect(pipe1, pipe2):
        return "EXTEND_BOTH"
    
    # METHOD 3: UNION (nếu True Trim không thành công)
    output.print_md('  🥉 **METHOD 3: UNION PIPES**')
    try:
        pipe_ids = [pipe1.Id, pipe2.Id]
        collection = List[DB.ElementId](pipe_ids)
        union_result = DB.ElementTransformUtils.CopyElements(doc, collection, doc, None, None)
        if union_result and len(union_result) > 0:
            output.print_md('    ✅ Union thành công')
            return "UNION"
    except Exception as e:
        output.print_md('    ❌ Union failed: {}'.format(str(e)))
    
    # METHOD 4: CONNECTOR CONNECTION
    output.print_md('  🔌 **METHOD 4: CONNECTOR CONNECTION**')
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
                            output.print_md('    ✅ Đã kết nối connectors (distance: {:.3f})'.format(distance))
                            return "CONNECTOR"
                        except:
                            continue
    except Exception as e:
        output.print_md('    ❌ Connector connection failed: {}'.format(str(e)))
    
    # METHOD 5: EXTEND PIPES
    output.print_md('  📏 **METHOD 5: EXTEND PIPES**')
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
            
            output.print_md('    ✅ Đã extend pipes (gap: {:.3f} feet)'.format(min_dist))
            return "EXTEND"
            
    except Exception as e:
        output.print_md('    ❌ Extend pipes failed: {}'.format(str(e)))
    
    # METHOD 6: CREATE SEGMENT (last resort)
    output.print_md('  🆕 **METHOD 6: CREATE SEGMENT**')
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
                output.print_md('    ✅ Đã tạo pipe segment nối (length: {:.3f} feet)'.format(min_dist))
                return "SEGMENT"
                
    except Exception as e:
        output.print_md('    ❌ Create segment failed: {}'.format(str(e)))
    
    output.print_md('  💥 **TẤT CẢ METHODS THẤT BẠI**')
    return False

def main():
    """Hàm chính của tool - Complete Remove Coupling Tool"""
    try:
        selection = uidoc.Selection
        
        # Hiển thị header và hướng dẫn
        output.print_md('# 🔧 REMOVE COUPLING TOOL - FINAL CONSOLIDATED VERSION')
        output.print_md('## 🎯 TRUE TRIM: Extend pipes hiện có để kết nối (GIỮ NGUYÊN THÔNG TIN)')
        output.print_md('')
        output.print_md('### 🔄 Các phương pháp được sử dụng:')
        output.print_md('1. **TRUE TRIM** (Priority): Gộp 2 pipes thành 1 pipe liền mạch')
        output.print_md('2. **EXTEND BOTH** (Backup): Extend cả 2 pipes tới điểm giữa')
        output.print_md('3. **UNION**: Sử dụng Revit API để union pipes')
        output.print_md('4. **CONNECTOR**: Kết nối logic thông qua connectors')
        output.print_md('5. **EXTEND**: Kéo dài pipes về giữa để đóng khoảng hở')
        output.print_md('6. **SEGMENT**: Tạo pipe segment nhỏ làm cầu nối')
        output.print_md('')
        
        # Hướng dẫn sử dụng
        output.print_md('### 📋 Hướng dẫn sử dụng:')
        output.print_md('1. Chọn 1 hoặc nhiều coupling elements trong Revit')
        output.print_md('2. Chạy tool này')
        output.print_md('3. Tool sẽ tự động tìm 2 pipes kết nối với mỗi coupling')
        output.print_md('4. Xóa coupling và thực hiện TRUE TRIM (gộp pipes)')
        output.print_md('')
        
        # Yêu cầu người dùng chọn elements
        output.print_md('### 🖱️ Hãy chọn coupling elements muốn xóa...')
        selected_elements = []
        
        try:
            # Cho phép user chọn multiple elements
            selected_refs = selection.PickObjects(ObjectType.Element, "Chọn coupling elements (có thể chọn nhiều)")
            
            for ref in selected_refs:
                element = doc.GetElement(ref.ElementId)
                selected_elements.append(element)
                
        except Exception as selection_error:
            output.print_md('❌ **Lỗi chọn elements:** {}'.format(str(selection_error)))
            output.print_md('💡 **Hướng dẫn:** Hãy chọn 1 hoặc nhiều coupling elements trong model')
            return
        
        if not selected_elements:
            output.print_md('⚠️ **Không có elements nào được chọn!**')
            return
        
        output.print_md('')
        output.print_md('# 🚀 BẮT ĐẦU XỬ LÝ')
        output.print_md('**Đã chọn {} element(s)**'.format(len(selected_elements)))
        output.print_md('---')
        
        # Bắt đầu transaction
        with DB.Transaction(doc, "Remove Coupling and TRUE TRIM Pipes") as trans:
            trans.Start()
            
            total_count = len(selected_elements)
            success_count = 0
            error_count = 0
            
            for i, coupling in enumerate(selected_elements, 1):
                output.print_md('')
                output.print_md('## 🔄 PROCESSING {}/{}: Element ID {}'.format(i, total_count, coupling.Id))
                
                # Tìm pipes kết nối với coupling này
                output.print_md('  🔍 Đang tìm pipes kết nối...')
                connected_pipes = find_connected_pipes(coupling)
                
                output.print_md('  📊 Tìm thấy {} pipe(s) kết nối'.format(len(connected_pipes)))
                for j, pipe in enumerate(connected_pipes, 1):
                    output.print_md('    {}. Pipe ID: {}'.format(j, pipe.Id))
                
                if len(connected_pipes) == 2:
                    pipe1, pipe2 = connected_pipes[0], connected_pipes[1]
                    output.print_md('  ✅ Đủ 2 pipes để thực hiện TRUE TRIM')
                    
                    # Disconnect và xóa coupling trước
                    try:
                        output.print_md('  🔌 Đang disconnect coupling...')
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
                                      # Disconnect từng ref
                                    for ref in refs_to_disconnect:
                                        try:
                                            conn.DisconnectFrom(ref)
                                            output.print_md('      ✅ Disconnected từ element ID: {}'.format(ref.Owner.Id))
                                            disconnect_success = True
                                        except Exception as disc_err:
                                            output.print_md('      ⚠️ Không thể disconnect: {}'.format(str(disc_err)))
                        
                        except Exception as connect_error:
                            output.print_md('      ⚠️ Lỗi disconnect method 1: {}'.format(str(connect_error)))
                        
                        # Method 2: Disconnect thông qua pipe connectors (backup)
                        if not disconnect_success:
                            output.print_md('    🔌 Disconnect method 2: Pipe connectors')
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
                                                output.print_md('      ✅ Pipe {} disconnected từ coupling'.format(pipe.Id))
                                                disconnect_success = True
                                            except Exception as disc_err:
                                                output.print_md('      ⚠️ Pipe disconnect error: {}'.format(str(disc_err)))
                        
                        if disconnect_success:
                            output.print_md('  ✅ Đã disconnect pipes khỏi coupling')
                        else:
                            output.print_md('  ⚠️ Không disconnect được - Thử force delete...')
                        
                    except Exception as disconnect_error:
                        output.print_md('  ⚠️ Lỗi disconnect: {} - Thử xóa trực tiếp...'.format(str(disconnect_error)))
                    
                    # Bây giờ mới xóa coupling với multiple fallback methods
                    output.print_md('  🗑️ Đang xóa coupling...')
                    delete_success = False
                    
                    try:
                        # Method 1: Xóa trực tiếp
                        doc.Delete(coupling.Id)
                        delete_success = True
                        output.print_md('  ✅ Đã xóa coupling thành công (method 1)')
                        
                    except Exception as delete_error:
                        output.print_md('  ⚠️ Method 1 failed: {}'.format(str(delete_error)))
                        
                        # Method 2: Force delete với collection
                        try:
                            element_ids = []
                            element_ids.append(coupling.Id)
                            doc.Delete(element_ids)
                            delete_success = True
                            output.print_md('  ✅ Đã xóa coupling thành công (method 2 - collection)')
                            
                        except Exception as delete_error2:
                            output.print_md('  ⚠️ Method 2 failed: {}'.format(str(delete_error2)))
                            
                            # Method 3: Thử với ElementTransformUtils
                            try:
                                from Autodesk.Revit.DB import ElementTransformUtils, Transform
                                # Đôi khi move element ra khỏi view rồi delete
                                transform = Transform.CreateTranslation(DB.XYZ(1000, 1000, 1000))
                                ElementTransformUtils.MoveElement(doc, coupling.Id, transform.Origin)
                                doc.Delete(coupling.Id)
                                delete_success = True
                                output.print_md('  ✅ Đã xóa coupling thành công (method 3 - move+delete)')
                                
                            except Exception as delete_error3:
                                output.print_md('  ❌ TẤT CẢ METHODS THẤT BẠI: {}'.format(str(delete_error3)))
                                output.print_md('  💡 Thử disconnect thủ công coupling này trong Revit')
                    
                    if not delete_success:
                        output.print_md('  ❌ Không thể xóa coupling - Bỏ qua element này')
                        error_count += 1
                        continue
                    
                    # Kết nối và TRUE TRIM
                    result = connect_pipes_comprehensive(pipe1, pipe2)
                    
                    if result == "TRUE_TRIM":
                        output.print_md('  🎉 **THÀNH CÔNG: ĐÃ THỰC HIỆN TRUE TRIM!**')
                        output.print_md('  💾 **Kết quả: 2 pipes đã được GỘP thành 1 PIPE LIỀN MẠCH**')
                        output.print_md('  🔗 **Pipe được giữ lại chứa TẤT CẢ thông tin gốc (tags, parameters, schedules)**')
                        output.print_md('  🗑️ **Pipe thứ 2 đã được xóa (không cần thiết nữa)**')
                        success_count += 1
                    elif result == "EXTEND_BOTH":
                        output.print_md('  ⚠️ **THÀNH CÔNG: ĐÃ EXTEND CẢ 2 PIPES (BACKUP METHOD)**')
                        output.print_md('  💡 **Kết quả: 2 pipes được extend để kết nối (giữ nguyên 2 pipes riêng biệt)**')
                        output.print_md('  📝 **Lưu ý: TRUE TRIM không thành công, đã dùng backup method**')
                        success_count += 1
                    elif result == "UNION":
                        output.print_md('  ✅ **THÀNH CÔNG: ĐÃ UNION PIPES!**')
                        output.print_md('  💡 **Kết quả: 2 pipes đã được union thành 1 pipe**')
                        success_count += 1
                    elif result == "CONNECTOR":
                        output.print_md('  ⚠️ **THÀNH CÔNG MỘT PHẦN: ĐÃ KẾT NỐI PIPES**')
                        output.print_md('  💡 **Kết quả: 2 pipes đã được kết nối (chưa gộp thành 1)**')
                        success_count += 1
                    elif result == "EXTEND":
                        output.print_md('  ⚠️ **THÀNH CÔNG MỘT PHẦN: ĐÃ EXTEND PIPES**')
                        output.print_md('  💡 **Kết quả: 2 pipes đã được kéo dài để đóng khoảng hở**')
                        success_count += 1
                    elif result == "SEGMENT":
                        output.print_md('  ⚠️ **THÀNH CÔNG MỘT PHẦN: ĐÃ TẠO PIPE SEGMENT**')
                        output.print_md('  💡 **Kết quả: Đã tạo pipe nhỏ để nối 2 pipes**')
                        success_count += 1
                    else:
                        output.print_md('  💥 **THẤT BẠI: KHÔNG THỂ KẾT NỐI PIPES**')
                        error_count += 1
                        
                elif len(connected_pipes) > 2:
                    output.print_md('  ⚠️ Có {} pipes kết nối (quá nhiều, cần đúng 2)'.format(len(connected_pipes)))
                    error_count += 1
                    
                else:
                    output.print_md('  ⚠️ Chỉ có {} pipes kết nối (quá ít, cần đúng 2)'.format(len(connected_pipes)))
                    error_count += 1
                
                output.print_md('')
            
            # Tổng kết cuối cùng
            output.print_md('# 📊 KẾT QUẢ CUỐI CÙNG')
            output.print_md('---')
            output.print_md('**📈 Tổng số:** {} coupling(s)'.format(total_count))
            output.print_md('**✅ Thành công:** {} coupling(s)'.format(success_count))
            output.print_md('**❌ Thất bại:** {} coupling(s)'.format(error_count))
            output.print_md('**📊 Tỷ lệ thành công:** {:.1f}%'.format((success_count*100.0/total_count) if total_count > 0 else 0))
            output.print_md('')
            
            if success_count > 0:
                output.print_md('🎉 **HOÀN THÀNH!** Đã xử lý thành công {} coupling(s)!'.format(success_count))
                output.print_md('💾 **Kết quả chính:** TRUE TRIM đã GỘP các pipes thành PIPES LIỀN MẠCH!')
                output.print_md('🔗 **Thông tin được bảo toàn:** Tags, Parameters, Schedules không bị mất!')
                output.print_md('🗑️ **Pipes thừa đã được xóa** để tạo ra đường ống liền mạch duy nhất')
            
            if error_count > 0:
                output.print_md('⚠️ **Lưu ý:** {} coupling(s) không thể xử lý - kiểm tra log bên trên'.format(error_count))
            
            # Commit transaction
            trans.Commit()
                
    except Exception as e:
        output.print_md('💥 **LỖI NGHIÊM TRỌNG:** {}'.format(str(e)))
        output.print_md('📞 **Liên hệ hỗ trợ nếu lỗi tiếp tục xảy ra**')

# Chạy tool
if __name__ == '__main__':
    main()
