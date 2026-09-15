import math


def point_to_segment_distance(px, py, x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    
    if dx == 0 and dy == 0:
        return math.sqrt((px - x1)**2 + (py - y1)**2)
    
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    
    nearest_x = x1 + t * dx
    nearest_y = y1 + t * dy
    
    return math.sqrt((px - nearest_x)**2 + (py - nearest_y)**2)


def segment_circle_collision(x1, y1, x2, y2, cx, cy, radius):
    dist = point_to_segment_distance(cx, cy, x1, y1, x2, y2)
    return dist < radius


def segment_circle_collision_with_point(x1, y1, x2, y2, cx, cy, radius):
    dist = point_to_segment_distance(cx, cy, x1, y1, x2, y2)
    
    if dist < radius:
        dx = x2 - x1
        dy = y2 - y1
        
        if dx == 0 and dy == 0:
            closest_x, closest_y = x1, y1
        else:
            t = ((cx - x1) * dx + (cy - y1) * dy) / (dx * dx + dy * dy)
            t = max(0.0, min(1.0, t))
            closest_x = x1 + t * dx
            closest_y = y1 + t * dy
        
        return True, (closest_x, closest_y)
    
    return False, None


def trajectory_circle_collision(trajectory, cx, cy, radius):
    if len(trajectory) < 2:
        return False, None
    
    for i in range(len(trajectory) - 1):
        x1, y1 = trajectory[i]
        x2, y2 = trajectory[i + 1]
        
        hit, point = segment_circle_collision_with_point(x1, y1, x2, y2, cx, cy, radius)
        if hit:
            return True, point
    
    return False, None


def slice_collision(slash_event, fruits):
    hit_fruits = []

    if slash_event is None:
        return hit_fruits

    if slash_event.trajectory and len(slash_event.trajectory) >= 2:
        trajectory = slash_event.trajectory
    else:
        trajectory = []
        start_x, start_y = slash_event.start_pos
        end_x, end_y = slash_event.end_pos

        num_points = max(5, int(slash_event.length / 10))
        num_points = min(num_points, 20)

        for i in range(num_points + 1):
            t = i / num_points
            x = start_x + t * (end_x - start_x)
            y = start_y + t * (end_y - start_y)
            trajectory.append((x, y))

    for fruit in fruits:
        if hasattr(fruit, 'is_sliced') and fruit.is_sliced:
            continue
        if hasattr(fruit, 'is_exploded') and fruit.is_exploded:
            continue
        if hasattr(fruit, 'is_active') and not fruit.is_active:
            continue

        hit, point = trajectory_circle_collision(
            trajectory,
            fruit.x,
            fruit.y,
            fruit.radius
        )

        if hit:
            hit_fruits.append((fruit, point))

    return hit_fruits


def slice_collision_with_trajectory(trajectory, fruits):
    hit_fruits = []
    
    if not trajectory or len(trajectory) < 2:
        return hit_fruits
    
    for fruit in fruits:
        if hasattr(fruit, 'is_sliced') and fruit.is_sliced:
            continue
        if hasattr(fruit, 'is_exploded') and fruit.is_exploded:
            continue
        if hasattr(fruit, 'is_active') and not fruit.is_active:
            continue
        
        hit, point = trajectory_circle_collision(
            trajectory,
            fruit.x,
            fruit.y,
            fruit.radius
        )
        
        if hit:
            hit_fruits.append((fruit, point))
    
    return hit_fruits


def point_circle_collision(px, py, cx, cy, radius):
    dx = px - cx
    dy = py - cy
    return math.sqrt(dx * dx + dy * dy) < radius