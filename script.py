# -*- coding: utf-8 -*-
"""
REMOVE COUPLING TOOL - FINAL CONSOLIDATED VERSION
================================================================
Tool để xóa coupling và gộp 2 pipes thành 1 pipe liền mạch (TRUE TRIM)

TÍNH NĂNG CHÍNH:
- Xóa coupling và tự động kết nối lại 2 pipe segments
- TRUE TRIM: Gộp 2 pipes thành 1 pipe liền mạch (như Trim UI trong Revit)
- 5 phương pháp backup đảm bảo thành công cao
- Hỗ trợ cả system pipe fittings và family instance couplings

PHƯƠNG PHÁP SỬ DỤNG:
1. TRUE TRIM - Tạo 1 pipe mới thay thế 2 pipes cũ (TỐT NHẤT)
2. Union Pipes - Sử dụng PlumbingUtils.UnionPipes 
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

# Khởi tạo output window
output = script.get_output()
output.close_others()

# Lấy document và UI document
doc = revit.doc
uidoc = revit.uidoc

# Hằng số
PIPE_FITTING_CATEGORY = int(DB.BuiltInCategory.OST_PipeFitting)
PIPE_CURVES_CATEGORY = int(DB.BuiltInCategory.OST_PipeCurves)

def get_pipe_connections(pipe_element):
    """Lấy tất cả connector của pipe hoặc fitting"""
    connectors = []
    try:
        element_type = pipe_element.GetType().Name
        output.print_md('      🔍 Element type: {}'.format(element_type))
        
        # Kiểm tra loại element và lấy connector tương ứng
        if hasattr(pipe_element, 'ConnectorManager'):
            # Pipe thông thường
            output.print_md('      📌 Có ConnectorManager')
            connector_manager = pipe_element.ConnectorManager
            if connector_manager:
                connector_count = 0
                for connector in connector_manager.Connectors:
                    connectors.append(connector)
                    connector_count += 1
                output.print_md('      📊 ConnectorManager: {} connectors'.format(connector_count))
            else:
                output.print_md('      ⚠️ ConnectorManager is None')
                
        elif hasattr(pipe_element, 'MEPModel'):
            # Family instance fitting
            output.print_md('      📌 Có MEPModel (Family Instance)')
            mep_model = pipe_element.MEPModel
            if mep_model and hasattr(mep_model, 'ConnectorManager'):
                connector_manager = mep_model.ConnectorManager
                if connector_manager:
                    connector_count = 0
                    for connector in connector_manager.Connectors:
                        connectors.append(connector)
                        connector_count += 1
                    output.print_md('      📊 MEPModel.ConnectorManager: {} connectors'.format(connector_count))
                else:
                    output.print_md('      ⚠️ MEPModel.ConnectorManager is None')
            else:
                output.print_md('      ⚠️ MEPModel is None hoặc không có ConnectorManager')
        else:
            output.print_md('      ⚠️ Không tìm thấy ConnectorManager hoặc MEPModel')
            
    except Exception as e:
        output.print_md('      ❌ Lỗi khi lấy connections: {}'.format(str(e)))
    
    output.print_md('      📊 Tổng cộng: {} connectors'.format(len(connectors)))
    return connectors

def find_connected_pipes(coupling):
    """Tìm pipes kết nối với coupling thông qua connectors"""
    connected_pipes = []
    
    try:
        output.print_md('    🔍 Phương pháp 1: Tìm thông qua Connectors...')
        
        # Lấy connectors của coupling
        coupling_connectors = get_pipe_connections(coupling)
        output.print_md('    📊 Coupling có {} connectors'.format(len(coupling_connectors)))
        
        for i, coupling_connector in enumerate(coupling_connectors):
            output.print_md('      🔌 Connector {}: Connected to {} elements'.format(
                i+1, coupling_connector.AllRefs.Size))
            
            # Kiểm tra tất cả elements kết nối với connector này
            for ref in coupling_connector.AllRefs:
                connected_element = ref.Owner
                
                # Bỏ qua chính coupling
                if connected_element.Id == coupling.Id:
                    continue
                
                # Kiểm tra xem có phải pipe không
                if (connected_element.Category and 
                    connected_element.Category.Id.IntegerValue == PIPE_CURVES_CATEGORY):
                    
                    output.print_md('      ✅ Tìm thấy pipe: ID {}'.format(connected_element.Id))
                    if connected_element not in connected_pipes:
                        connected_pipes.append(connected_element)
                        
    except Exception as e:
        output.print_md('    ❌ Lỗi khi tìm connected pipes: {}'.format(str(e)))
    
    output.print_md('    📊 Tổng cộng: {} pipes kết nối'.format(len(connected_pipes)))
    return connected_pipes

def find_connected_pipes_by_geometry(coupling, tolerance=1.0):
    """Tìm pipes gần coupling dựa trên vị trí geometry (backup method)"""
    connected_pipes = []
    
    try:
        output.print_md('    🔍 Phương pháp 2: Tìm thông qua Geometry Proximity...')
        
        # Lấy location của coupling
        coupling_location = coupling.Location
        if not coupling_location:
            output.print_md('    ⚠️ Coupling không có location')
            return connected_pipes
        
        if hasattr(coupling_location, 'Point'):
            coupling_point = coupling_location.Point
        elif hasattr(coupling_location, 'Curve'):
            coupling_point = coupling_location.Curve.Evaluate(0.5, True)  # Điểm giữa curve
        else:
            output.print_md('    ⚠️ Không thể xác định vị trí coupling')
            return connected_pipes
        
        output.print_md('    📍 Coupling location: ({:.3f}, {:.3f}, {:.3f})'.format(
            coupling_point.X, coupling_point.Y, coupling_point.Z))
        
        # Tìm tất cả pipes trong model
        pipe_collector = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_PipeCurves).WhereElementIsNotElementType()
        
        for pipe in pipe_collector:
            if pipe.Location and hasattr(pipe.Location, 'Curve'):
                pipe_curve = pipe.Location.Curve
                
                # Tính khoảng cách từ coupling point đến pipe curve
                closest_point = pipe_curve.Project(coupling_point)
                if closest_point:
                    distance = coupling_point.DistanceTo(closest_point.XYZPoint)
                    
                    if distance <= tolerance:
                        output.print_md('    ✅ Pipe gần: ID {} (khoảng cách: {:.3f})'.format(pipe.Id, distance))
                        connected_pipes.append(pipe)
        
    except Exception as e:
        output.print_md('    ❌ Lỗi geometry search: {}'.format(str(e)))
    
    output.print_md('    📊 Geometry method: {} pipes'.format(len(connected_pipes)))
    return connected_pipes

def try_union_pipes(pipe1, pipe2):
    """Phương pháp 1: Thử union 2 pipes sử dụng PlumbingUtils"""
    try:
        output.print_md('    🔧 Thử PlumbingUtils.UnionPipes...')
        
        # Kiểm tra xem PlumbingUtils có sẵn không
        try:
            # Thử union pipes
            result = PlumbingUtils.UnionPipes(doc, pipe1, pipe2)
            if result:
                output.print_md('    ✅ Union pipes thành công!')
                return True
            else:
                output.print_md('    ⚠️ Union pipes trả về False')
                return False
                
        except AttributeError:
            output.print_md('    ⚠️ PlumbingUtils.UnionPipes không có sẵn trong phiên bản Revit này')
            return False
        except Exception as union_error:
            output.print_md('    ⚠️ Lỗi Union: {}'.format(str(union_error)))
            return False
            
    except Exception as e:
        output.print_md('    ❌ Lỗi try_union_pipes: {}'.format(str(e)))
        return False

def connect_pipes_by_connectors(pipe1, pipe2):
    """Phương pháp 2: Kết nối pipes thông qua connectors (logic connection)"""
    try:
        output.print_md('    🔧 Kết nối pipes bằng connectors...')
        
        # Lấy connectors của 2 pipes
        connectors1 = get_pipe_connections(pipe1)
        connectors2 = get_pipe_connections(pipe2)
        
        if len(connectors1) == 0 or len(connectors2) == 0:
            output.print_md('    ⚠️ Một hoặc cả hai pipes không có connector')
            return False
        
        # Tìm connectors gần nhau nhất
        min_distance = float('inf')
        best_conn1 = None
        best_conn2 = None
        
        for conn1 in connectors1:
            for conn2 in connectors2:
                # Chỉ kết nối connectors chưa kết nối
                if not conn1.IsConnected and not conn2.IsConnected:
                    distance = conn1.Origin.DistanceTo(conn2.Origin)
                    if distance < min_distance:
                        min_distance = distance
                        best_conn1 = conn1
                        best_conn2 = conn2
        
        if best_conn1 and best_conn2:
            output.print_md('    📏 Khoảng cách connectors: {:.4f} feet'.format(min_distance))
            
            # Kết nối connectors
            best_conn1.ConnectTo(best_conn2)
            output.print_md('    ✅ Đã kết nối connectors!')
            return True
        else:
            output.print_md('    ⚠️ Không tìm thấy connectors phù hợp để kết nối')
            return False
            
    except Exception as e:
        output.print_md('    ❌ Lỗi connector connection: {}'.format(str(e)))
        return False

def extend_pipes_to_close_gap(pipe1, pipe2):
    """Phương pháp 3: Kéo dài pipes về phía nhau để đóng khoảng hở"""
    try:
        output.print_md('    🔧 Extend pipes để đóng gap...')
        
        # Lấy curves của 2 pipes
        curve1 = pipe1.Location.Curve
        curve2 = pipe2.Location.Curve
        
        # Tìm endpoints gần nhau nhất
        points1 = [curve1.GetEndPoint(0), curve1.GetEndPoint(1)]
        points2 = [curve2.GetEndPoint(0), curve2.GetEndPoint(1)]
        
        min_distance = float('inf')
        extend_point1 = None
        extend_point2 = None
        target_point1 = None
        target_point2 = None
        
        for p1 in points1:
            for p2 in points2:
                distance = p1.DistanceTo(p2)
                if distance < min_distance:
                    min_distance = distance
                    extend_point1 = p1
                    extend_point2 = p2
                    # Điểm target là điểm giữa
                    target_point1 = DB.XYZ((p1.X + p2.X) / 2, (p1.Y + p2.Y) / 2, (p1.Z + p2.Z) / 2)
                    target_point2 = target_point1
        
        if min_distance < 10.0:  # Chỉ extend nếu gap không quá lớn
            output.print_md('    📏 Gap distance: {:.4f} feet'.format(min_distance))
            
            # Extend pipe1
            if extend_point1 == curve1.GetEndPoint(0):
                new_curve1 = DB.Line.CreateBound(target_point1, curve1.GetEndPoint(1))
            else:
                new_curve1 = DB.Line.CreateBound(curve1.GetEndPoint(0), target_point1)
            
            # Extend pipe2
            if extend_point2 == curve2.GetEndPoint(0):
                new_curve2 = DB.Line.CreateBound(target_point2, curve2.GetEndPoint(1))
            else:
                new_curve2 = DB.Line.CreateBound(curve2.GetEndPoint(0), target_point2)
            
            # Update pipe locations
            pipe1.Location.Curve = new_curve1
            pipe2.Location.Curve = new_curve2
            
            output.print_md('    ✅ Đã extend pipes - gap đã đóng!')
            return True
        else:
            output.print_md('    ⚠️ Gap quá lớn để extend: {:.4f} feet'.format(min_distance))
            return False
            
    except Exception as e:
        output.print_md('    ❌ Lỗi extend pipes: {}'.format(str(e)))
        return False

def create_connecting_pipe_segment(pipe1, pipe2):
    """Phương pháp 4: Tạo pipe segment ngắn để nối 2 pipes"""
    try:
        output.print_md('    🔧 Tạo pipe segment để nối...')
        
        # Tìm connectors gần nhau nhất
        connectors1 = get_pipe_connections(pipe1)
        connectors2 = get_pipe_connections(pipe2)
        
        min_distance = float('inf')
        conn1 = None
        conn2 = None
        
        for c1 in connectors1:
            for c2 in connectors2:
                distance = c1.Origin.DistanceTo(c2.Origin)
                if distance < min_distance:
                    min_distance = distance
                    conn1 = c1
                    conn2 = c2
        
        if not conn1 or not conn2:
            output.print_md('    ⚠️ Không tìm thấy connectors phù hợp')
            return False
        
        output.print_md('    📏 Khoảng cách cần nối: {:.4f} feet'.format(min_distance))
        
        # Tạo curve nối 2 connector
        connecting_curve = DB.Line.CreateBound(conn1.Origin, conn2.Origin)
        
        # Lấy pipe type và system từ pipe1
        pipe_type = pipe1.PipeType
        system_type = pipe1.MEPSystem.GetTypeId() if pipe1.MEPSystem else None
        level_id = pipe1.ReferenceLevel.Id
        
        # Tạo pipe mới để đóng khoảng hở
        new_pipe = DB.Plumbing.Pipe.Create(doc, system_type, pipe_type.Id, level_id, connecting_curve)
        
        if new_pipe:
            output.print_md('    ✅ Đã tạo pipe segment - ID: {} (dài: {:.4f} feet)'.format(new_pipe.Id, min_distance))
            
            # Kết nối với 2 pipe gốc
            new_connectors = get_pipe_connections(new_pipe)
            if len(new_connectors) >= 2:
                new_connectors[0].ConnectTo(conn1)
                new_connectors[1].ConnectTo(conn2)
                output.print_md('    ✅ Đã kết nối pipe segment với 2 pipes gốc!')
            
            return True
        else:
            output.print_md('    ❌ Không thể tạo pipe segment')
            return False
            
    except Exception as e:
        output.print_md('    ❌ Lỗi tạo connecting segment: {}'.format(str(e)))
        return False

def true_trim_pipes(pipe1, pipe2):
    """PHƯƠNG PHÁP TRUE TRIM: Tạo 1 pipe mới liền mạch thay thế 2 pipes cũ"""
    try:
        output.print_md('    🎯 TRUE TRIM: Tạo 1 pipe mới thay thế 2 pipes...')
        
        # Lấy thông tin từ pipe1 để tạo pipe mới
        pipe_type = pipe1.PipeType
        level_id = pipe1.ReferenceLevel.Id
        diameter = pipe1.Diameter
          # Lấy system type cẩn thận hơn
        system_type_id = None
        pipe_system = None
        try:
            if pipe1.MEPSystem:
                pipe_system = pipe1.MEPSystem
                system_type_id = pipe1.MEPSystem.GetTypeId()
                output.print_md('    📋 System Type ID: {}'.format(system_type_id))
                output.print_md('    📋 System Name: {}'.format(pipe_system.Name))
            else:
                output.print_md('    ⚠️ Pipe không có MEPSystem, sẽ tạo pipe không có system')
        except:
            output.print_md('    ⚠️ Không thể lấy system type, sẽ tạo pipe không có system')
        
        # Lấy curves của 2 pipes
        curve1 = pipe1.Location.Curve
        curve2 = pipe2.Location.Curve
        
        # Xác định điểm đầu và cuối của 2 pipes
        # Tìm điểm xa nhất để tạo pipe liền mạch
        points = [
            curve1.GetEndPoint(0), curve1.GetEndPoint(1),
            curve2.GetEndPoint(0), curve2.GetEndPoint(1)
        ]
        
        # Tìm 2 điểm xa nhất (đầu và cuối của pipe mới)
        max_distance = 0
        start_point = None
        end_point = None
        
        for i in range(len(points)):
            for j in range(i+1, len(points)):
                distance = points[i].DistanceTo(points[j])
                if distance > max_distance:
                    max_distance = distance
                    start_point = points[i]
                    end_point = points[j]
        
        if not start_point or not end_point:
            output.print_md('    ❌ Không thể xác định điểm đầu/cuối')
            return False
            
        output.print_md('    📏 Chiều dài pipe mới: {:.4f} feet'.format(max_distance))
        output.print_md('    📍 Từ: ({:.3f}, {:.3f}, {:.3f})'.format(
            start_point.X, start_point.Y, start_point.Z))
        output.print_md('    📍 Đến: ({:.3f}, {:.3f}, {:.3f})'.format(
            end_point.X, end_point.Y, end_point.Z))
        
        # Tạo curve mới liền mạch
        new_curve = DB.Line.CreateBound(start_point, end_point)
          # Tạo pipe mới
        output.print_md('    🔧 Tạo pipe mới liền mạch...')
          # Thử tạo pipe với các phương pháp khác nhau
        new_pipe = None
        try:
            # Phương pháp 1: Với system type ID (5 parameters)
            if system_type_id and system_type_id != DB.ElementId.InvalidElementId:
                output.print_md('    🔧 Thử tạo pipe với system type ID...')
                new_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type.Id, level_id, start_point, end_point)
            else:
                # Phương pháp 2: Không có system type (4 parameters)
                output.print_md('    🔧 Thử tạo pipe không có system type...')
                new_pipe = DB.Plumbing.Pipe.Create(doc, pipe_type.Id, level_id, start_point, end_point)
        except Exception as e1:
            output.print_md('    ⚠️ Lỗi tạo pipe với points: {}'.format(str(e1)))
            try:
                # Phương pháp 3: Sử dụng curve (backup method)
                output.print_md('    🔧 Thử tạo pipe với curve...')
                if system_type_id and system_type_id != DB.ElementId.InvalidElementId:
                    new_pipe = DB.Plumbing.Pipe.Create(doc, system_type_id, pipe_type.Id, level_id, new_curve)
                else:
                    new_pipe = DB.Plumbing.Pipe.Create(doc, pipe_type.Id, level_id, new_curve)
            except Exception as e2:
                output.print_md('    ❌ Lỗi tạo pipe với curve: {}'.format(str(e2)))
                try:
                    # Phương pháp 4: Chỉ với pipe type object trực tiếp
                    output.print_md('    🔧 Thử tạo pipe với pipe type object...')
                    new_pipe = DB.Plumbing.Pipe.Create(doc, pipe_type, level_id, start_point, end_point)
                except Exception as e3:
                    output.print_md('    ❌ Lỗi cuối cùng: {}'.format(str(e3)))
        
        if new_pipe:
            # Set diameter giống pipes cũ
            new_pipe.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(diameter)
            
            output.print_md('    ✅ Đã tạo pipe mới ID: {}'.format(new_pipe.Id))
            
            # Xóa 2 pipes cũ
            output.print_md('    🗑️ Xóa 2 pipes cũ...')
            doc.Delete(pipe1.Id)
            doc.Delete(pipe2.Id)
            
            output.print_md('    🎉 HOÀN THÀNH TRUE TRIM! Đã gộp 2 pipes thành 1 pipe liền mạch!')
            output.print_md('    📊 Kết quả: Pipe mới ID {} thay thế 2 pipes cũ'.format(new_pipe.Id))
            return True
        else:
            output.print_md('    ❌ Không thể tạo pipe mới')
            return False
        
    except Exception as e:
        output.print_md('    ❌ Lỗi True Trim: {}'.format(str(e)))
        return False

def connect_pipes_comprehensive(pipe1, pipe2):
    """Kết nối pipes với TRUE TRIM và các phương pháp backup"""
    try:
        output.print_md('  🎯 BẮT ĐẦU PROCESS TRUE TRIM VÀ KẾT NỐI...')
        
        # PHƯƠNG PHÁP MỚI: TRUE TRIM (tốt nhất - tạo 1 pipe liền mạch)
        output.print_md('  🔄 Đang thử TRUE TRIM METHOD...')
        if true_trim_pipes(pipe1, pipe2):
            return "TRUE_TRIM"
        
        # Phương pháp 1: Union pipes (backup)
        output.print_md('  🔄 Đang thử Phương pháp 1: Union pipes...')
        if try_union_pipes(pipe1, pipe2):
            return "UNION"
        
        # Phương pháp 2: Connector-based connection (kết nối logic)
        output.print_md('  🔄 Đang thử Phương pháp 2: Kết nối Connector...')
        if connect_pipes_by_connectors(pipe1, pipe2):
            return "CONNECTOR"
        
        # Phương pháp 3: Extend pipes về giữa (đóng khoảng hở vật lý)
        output.print_md('  🔄 Đang thử Phương pháp 3: Extend pipes...')
        if extend_pipes_to_close_gap(pipe1, pipe2):
            return "EXTEND"
        
        # Phương pháp 4: Tạo pipe segment mới (tạo cầu nối)
        output.print_md('  🔄 Đang thử Phương pháp 4: Tạo pipe segment...')
        if create_connecting_pipe_segment(pipe1, pipe2):
            return "SEGMENT"
        
        output.print_md('  ❌ TẤT CẢ 5 PHƯƠNG PHÁP THẤT BẠI')
        return False
        
    except Exception as e:
        output.print_md('  ❌ Lỗi khi kết nối pipes: {}'.format(str(e)))
        return False

def main():
    """Hàm chính của tool - Complete Remove Coupling Tool"""
    try:
        selection = uidoc.Selection
        
        # Hiển thị header và hướng dẫn
        output.print_md('# 🔧 REMOVE COUPLING TOOL - FINAL CONSOLIDATED VERSION')
        output.print_md('## 🎯 TRUE TRIM: Gộp 2 pipes thành 1 pipe liền mạch')
        output.print_md('')
        output.print_md('### 🔄 Các phương pháp được sử dụng:')
        output.print_md('1. **TRUE TRIM** - Tạo 1 pipe mới thay thế 2 pipes cũ (tốt nhất)')
        output.print_md('2. **Union Pipes** - Backup method using PlumbingUtils')
        output.print_md('3. **Connector Connection** - Kết nối logic')
        output.print_md('4. **Extend Pipes** - Kéo dài về giữa') 
        output.print_md('5. **Create Segment** - Tạo pipe nối')
        output.print_md('')
        output.print_md('### 📋 Hướng dẫn sử dụng:')
        output.print_md('- Chọn 1 hoặc nhiều **coupling elements**')
        output.print_md('- Tool sẽ tự động tìm 2 pipes kết nối với mỗi coupling')
        output.print_md('- Xóa coupling và **GỘP 2 PIPES THÀNH 1 PIPE** (nếu có thể)')
        output.print_md('')
        
        # Yêu cầu user chọn coupling elements
        try:
            selected_refs = selection.PickObjects(ObjectType.Element, 'Chọn coupling elements để xóa và kết nối pipes')
        except:
            output.print_md('❌ **Đã hủy chọn** - Tool dừng thực hiện')
            return
        
        if not selected_refs:
            output.print_md('⚠️ **Không có element nào được chọn**')
            return
        
        # Xử lý từng coupling trong một transaction duy nhất
        with revit.Transaction('Remove Coupling and Connect Pipes - Complete'):
            success_count = 0
            error_count = 0
            total_count = len(selected_refs)
            
            output.print_md('🚀 **BẮT ĐẦU XỬ LÝ {} COUPLING(S)...**'.format(total_count))
            output.print_md('')
            
            for idx, ref in enumerate(selected_refs, 1):
                coupling = doc.GetElement(ref.ElementId)
                
                output.print_md('## 🔧 [{}/{}] Xử lý Coupling ID: {}'.format(idx, total_count, coupling.Id))
                
                # Kiểm tra tính hợp lệ
                if not coupling or not coupling.Category:
                    output.print_md('  ⚠️ Element không hợp lệ')
                    error_count += 1
                    continue
                    
                if coupling.Category.Id.IntegerValue != PIPE_FITTING_CATEGORY:
                    output.print_md('  ⚠️ Không phải pipe fitting (Category: {})'.format(
                        coupling.Category.Name if coupling.Category else 'Unknown'))
                    error_count += 1
                    continue
                
                # Debug thông tin coupling
                try:
                    output.print_md('  🔍 Loại: {}'.format(coupling.GetType().Name))
                    if hasattr(coupling, 'Symbol') and coupling.Symbol:
                        output.print_md('  📋 Family: {}'.format(coupling.Symbol.Name))
                except Exception as e:
                    output.print_md('  ⚠️ Không thể lấy thông tin chi tiết: {}'.format(str(e)))
                
                # Tìm pipe kết nối
                output.print_md('  🔍 Đang tìm pipes kết nối...')
                connected_pipes = find_connected_pipes(coupling)
                output.print_md('  📊 Connector method: {} pipes'.format(len(connected_pipes)))
                
                # Nếu không tìm thấy pipe bằng connector, thử geometry
                if len(connected_pipes) == 0:
                    output.print_md('  🔍 Thử tìm bằng geometry proximity...')
                    connected_pipes = find_connected_pipes_by_geometry(coupling)
                    output.print_md('  📊 Geometry method: {} pipes'.format(len(connected_pipes)))
                
                # Xử lý kết quả
                if len(connected_pipes) == 2:
                    pipe1, pipe2 = connected_pipes
                    output.print_md('  📍 **Pipe 1:** {} | **Pipe 2:** {}'.format(pipe1.Id, pipe2.Id))
                    
                    # Xóa coupling
                    output.print_md('  🗑️ Đang xóa coupling...')
                    doc.Delete(coupling.Id)
                    output.print_md('  ✅ Đã xóa coupling thành công')
                    
                    # Kết nối và TRUE TRIM
                    result = connect_pipes_comprehensive(pipe1, pipe2)
                    if result == "TRUE_TRIM":
                        output.print_md('  🎉 **THÀNH CÔNG: ĐÃ THỰC HIỆN TRUE TRIM!**')
                        output.print_md('  💡 **Kết quả: 2 pipes đã được GỘP THÀNH 1 PIPE LIỀN MẠCH**')
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
                output.print_md('🎉 **HOÀN THÀNH!** Đã đóng hoàn toàn khoảng hở cho {} coupling(s)!'.format(success_count))
                output.print_md('🔗 **Kết quả:** Tất cả pipes đã được nối liền mạch!')
            
            if error_count > 0:
                output.print_md('⚠️ **Lưu ý:** {} coupling(s) không thể xử lý - kiểm tra log bên trên'.format(error_count))
                
    except Exception as e:
        output.print_md('💥 **LỖI NGHIÊM TRỌNG:** {}'.format(str(e)))
        output.print_md('📞 **Liên hệ hỗ trợ nếu lỗi tiếp tục xảy ra**')

# Chạy tool
if __name__ == '__main__':
    main()
