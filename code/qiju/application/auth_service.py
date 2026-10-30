"""账号与登录（REQ-001/002/021）。"""

from __future__ import annotations

from datetime import timedelta

from ..domain.clock import iso
from ..domain.entities import Hotel, InvitationCode, User, new_id
from ..domain.enums import AuditAction, BusinessStatus, Role, UserStatus
from ..domain.errors import Conflict, NotFound, ValidationError
from ..domain.validation import (
    validate_contact_phone,
    validate_name,
    validate_phone,
)
from ..infrastructure.security import hash_password, verify_password
from .base import BaseService, Session


class AuthService(BaseService):
    """注册、登录、店长激活、前台子账号与邀请码。"""

    def register_customer(
        self, phone: str, password: str, display_name: str
    ) -> User:
        """顾客自助注册。手机号唯一由数据库兜底。"""
        phone = validate_phone(phone)
        name = validate_name(display_name, field="昵称")
        user = User(
            id=new_id(),
            phone=phone,
            password_hash=hash_password(password),
            role=Role.CUSTOMER,
            display_name=name,
            created_at=self.clock.now(),
        )
        with self.db.transaction():
            if self.repos.users.by_phone(phone) is not None:
                raise Conflict("该手机号不可用，请尝试登录或联系客服")
            self.repos.users.add(user)
            self.write_log(
                user=user,
                action=AuditAction.USER_CREATE,
                object_type="User",
                object_id=user.id,
                reason="顾客注册",
            )
        return user

    def login(self, phone: str, password: str) -> Session:
        """登录。失败提示不区分“账号不存在”和“密码错误”。"""
        user = self.repos.users.by_phone((phone or "").strip())
        if user is None or not verify_password(password, user.password_hash):
            raise ValidationError("手机号或密码错误")
        if not user.is_active:
            raise Conflict("账号已停用，请联系管理员")
        with self.db.transaction():
            self.write_log(
                user=user,
                action=AuditAction.LOGIN,
                object_type="User",
                object_id=user.id,
                reason="登录成功",
            )
        return Session(user=user)

    def activate_manager(
        self, code: str, phone: str, password: str, display_name: str
    ) -> Session:
        """店长用邀请码激活酒店账号。邀请码一次性、绑定酒店。"""
        phone = validate_phone(phone)
        name = validate_name(display_name)
        invitation = self.repos.invitations.by_code((code or "").strip().upper())
        if invitation is None:
            raise NotFound("邀请码不存在")
        now = self.clock.now()
        if not invitation.is_valid(now):
            raise Conflict("邀请码已使用或已过期")
        hotel = self.repos.hotels.by_id(invitation.hotel_id)
        if hotel is None:
            raise NotFound("邀请码对应的酒店不存在")
        user = User(
            id=new_id(),
            phone=phone,
            password_hash=hash_password(password),
            role=Role.MANAGER,
            display_name=name,
            hotel_id=hotel.id,
            created_at=now,
        )
        with self.db.transaction():
            if self.repos.users.by_phone(phone) is not None:
                raise Conflict("该手机号不可用，请尝试登录或联系客服")
            self.repos.users.add(user)
            self.repos.invitations.mark_used(invitation.code, user.id, now)
            self.write_log(
                user=user,
                action=AuditAction.USER_CREATE,
                object_type="User",
                object_id=user.id,
                hotel_id=hotel.id,
                reason=f"店长激活（邀请码 {invitation.code}）",
            )
        return Session(user=user)

    def create_front_desk(
        self, session: Session, phone: str, password: str, display_name: str
    ) -> User:
        """店长为所属酒店创建前台子账号（REQ-001）。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        if actor.hotel_id is None:
            raise Conflict("账号未绑定酒店")
        phone = validate_phone(phone)
        name = validate_name(display_name)
        user = User(
            id=new_id(),
            phone=phone,
            password_hash=hash_password(password),
            role=Role.FRONT_DESK,
            display_name=name,
            hotel_id=actor.hotel_id,
            created_at=self.clock.now(),
        )
        with self.db.transaction():
            if self.repos.users.by_phone(phone) is not None:
                raise Conflict("该手机号不可用")
            self.repos.users.add(user)
            self.write_log(
                user=actor,
                action=AuditAction.USER_CREATE,
                object_type="User",
                object_id=user.id,
                hotel_id=actor.hotel_id,
                reason=f"创建前台子账号：{name}",
            )
        return user

    def issue_invitation(
        self, session: Session, hotel_id: str, *, days: int = 7
    ) -> InvitationCode:
        """平台管理员签发店长邀请码（REQ-001）。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.PLATFORM_ADMIN)
        hotel = self.repos.hotels.by_id(hotel_id)
        if hotel is None:
            raise NotFound("酒店不存在")
        moment = self.clock.now()
        code = InvitationCode(
            code=new_id()[:8].upper(),
            hotel_id=hotel_id,
            created_by=actor.id,
            expires_at=moment + timedelta(days=days),
        )
        with self.db.transaction():
            self.repos.invitations.add(code)
            self.write_log(
                user=actor,
                action=AuditAction.HOTEL_SUBMIT,
                object_type="InvitationCode",
                object_id=code.code,
                hotel_id=hotel_id,
                after=f"有效期至 {iso(code.expires_at)}",
                reason="签发店长邀请码",
            )
        return code

    def create_hotel(
        self,
        session: Session,
        *,
        name: str,
        city: str,
        address: str,
        phone: str,
        description: str = "",
    ) -> Hotel:
        """平台管理员录入酒店（未审核、暂停营业），之后签发邀请码。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.PLATFORM_ADMIN)
        hotel = Hotel(
            id=new_id(),
            name=validate_name(name, field="酒店名称"),
            city=validate_name(city, field="城市"),
            address=validate_name(address, field="地址"),
            phone=validate_contact_phone(phone, field="联系电话"),
            business_status=BusinessStatus.SUSPENDED,
            description=description.strip(),
            created_at=self.clock.now(),
        )
        with self.db.transaction():
            self.repos.hotels.add(hotel)
            self.write_log(
                user=actor,
                action=AuditAction.HOTEL_SUBMIT,
                object_type="Hotel",
                object_id=hotel.id,
                hotel_id=hotel.id,
                after=f"{hotel.name}（{hotel.city}）",
                reason="平台录入酒店",
            )
        return hotel

    def disable_user(self, session: Session, user_id: str) -> None:
        """停用账号：店长可停用本店前台，管理员可停用任意账号。"""
        actor = self.require_active(session)
        target = self.repos.users.by_id(user_id)
        if target is None:
            raise NotFound("账号不存在")
        if actor.role is Role.MANAGER:
            if target.hotel_id != actor.hotel_id or target.role is not Role.FRONT_DESK:
                raise NotFound("账号不存在")
        elif actor.role is not Role.PLATFORM_ADMIN:
            self.require_role(actor, Role.PLATFORM_ADMIN)
        with self.db.transaction():
            self.repos.users.set_status(user_id, UserStatus.DISABLED)
            self.write_log(
                user=actor,
                action=AuditAction.USER_CREATE,
                object_type="User",
                object_id=user_id,
                hotel_id=target.hotel_id,
                before="ACTIVE",
                after="DISABLED",
                reason="停用账号",
            )

    def list_staff(self, session: Session) -> list[User]:
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        if actor.hotel_id is None:
            return []
        return self.repos.users.list_by_hotel(actor.hotel_id)
