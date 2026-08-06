import React, { useState, useEffect } from 'react';
import { UserService, UserProfile } from '../services/UserService';
import { fetchServerUsers, registerUser, loginUser } from '../services/api';
import { Users, UserPlus, Check, X, Shield, Sparkles, Lock, Key } from 'lucide-react';

interface UserDashboardModalProps {
  onClose: () => void;
  onUserChanged: (newUser: UserProfile) => void;
}

export const UserDashboardModal: React.FC<UserDashboardModalProps> = ({ onClose, onUserChanged }) => {
  const [allUsers, setAllUsers] = useState<UserProfile[]>(UserService.getAllUsers());
  const [activeUser, setActiveUser] = useState<UserProfile>(UserService.getActiveUser());
  const [showCreateForm, setShowCreateForm] = useState(false);

  const [newName, setNewName] = useState('');
  const [newRole, setNewRole] = useState('');
  const [newAvatarIcon, setNewAvatarIcon] = useState('👤');
  const [newPassword, setNewPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const AVATAR_ICONS = ['👑', '👤', '🎬', '🚀', '🎨', '💼', '🎧', '🔬'];

  const [targetUserForLogin, setTargetUserForLogin] = useState<UserProfile | null>(null);
  const [switchPassword, setSwitchPassword] = useState('');
  const [showSwitchPassword, setShowSwitchPassword] = useState(false);
  
  // Password setup state for active profile
  const [showSetPassForm, setShowSetPassForm] = useState(false);
  const [profileNewPassword, setProfileNewPassword] = useState('');
  const [profilePassSuccessMsg, setProfilePassSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchServerUsers().then((serverUsers) => {
      if (serverUsers && serverUsers.length > 0) {
        UserService.syncWithServer(serverUsers);
        setAllUsers(UserService.getAllUsers());
      }
    }).catch(() => {});
  }, []);

  const handleSelectUser = async (user: UserProfile) => {
    if (user.id === activeUser.id) return;
    setErrorMsg(null);

    // If target user has a password or if global protection might be active, prompt for password
    if (user.hasPassword) {
      setTargetUserForLogin(user);
      setSwitchPassword('');
      return;
    }

    // Try passwordless login
    try {
      const res = await loginUser(user.id);
      const updatedUser = res.user || user;
      setActiveUser(updatedUser);
      UserService.setActiveUser(updatedUser);
      onUserChanged(updatedUser);
      setTargetUserForLogin(null);
    } catch (e: any) {
      // If server requires password
      setTargetUserForLogin(user);
      setSwitchPassword('');
      setErrorMsg(e.message || `Password required to access ${user.name}'s profile.`);
    }
  };

  const handleSwitchSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetUserForLogin) return;

    try {
      setErrorMsg(null);
      const res = await loginUser(targetUserForLogin.id, switchPassword);
      const updatedUser = res.user || targetUserForLogin;
      setActiveUser(updatedUser);
      UserService.setActiveUser(updatedUser);
      onUserChanged(updatedUser);
      setTargetUserForLogin(null);
      setSwitchPassword('');
    } catch (e: any) {
      setErrorMsg(e.message || `Incorrect password for profile '${targetUserForLogin.name}'`);
    }
  };

  const handleSetProfilePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!profileNewPassword || profileNewPassword.length < 3) {
      setErrorMsg("Password must be at least 3 characters");
      return;
    }

    try {
      setErrorMsg(null);
      await registerUser(activeUser.name, activeUser.role, activeUser.avatarIcon, profileNewPassword);
      setProfilePassSuccessMsg(`✓ Password set successfully for profile '${activeUser.name}'!`);
      
      // Update local state
      const updatedList = allUsers.map(u => u.id === activeUser.id ? { ...u, hasPassword: true } : u);
      setAllUsers(updatedList);
      setShowSetPassForm(false);
      setProfileNewPassword('');
      setTimeout(() => setProfilePassSuccessMsg(null), 4000);
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to set profile password");
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;

    try {
      setErrorMsg(null);
      const res = await registerUser(newName, newRole, newAvatarIcon, newPassword);
      const createdUser: UserProfile = res.user || {
        id: res.user?.id || `user-${Date.now()}`,
        name: newName.trim(),
        avatarIcon: newAvatarIcon,
        role: newRole.trim() || 'Custom User',
        badgeColor: 'linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)',
        hasPassword: !!newPassword
      };

      UserService.createNewUser(createdUser.name, createdUser.role, createdUser.avatarIcon, createdUser.id);
      setAllUsers(UserService.getAllUsers());
      setActiveUser(createdUser);
      onUserChanged(createdUser);
      setShowCreateForm(false);
      setNewName('');
      setNewRole('');
      setNewPassword('');
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to create user account");
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(15, 23, 42, 0.65)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: '20px'
    }}>
      <div className="modal-card-responsive" style={{
        background: '#ffffff',
        borderRadius: '24px',
        width: '100%',
        maxWidth: '520px',
        maxHeight: '90vh',
        overflowY: 'auto',
        padding: '28px',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
        border: '1px solid rgba(226, 232, 240, 0.8)'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '44px', height: '44px', borderRadius: '14px', background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '22px' }}>
              👤
            </div>
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: 700, color: '#0f172a', margin: 0 }}>Multi-User Workspace Security</h3>
              <p style={{ fontSize: '12px', color: '#64748b', margin: 0 }}>Private custom models & isolated chat histories per user</p>
            </div>
          </div>
          <button onClick={onClose} style={{ background: '#f1f5f9', border: 'none', width: '32px', height: '32px', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
            <X size={18} color="#64748b" />
          </button>
        </div>

        {errorMsg && (
          <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', color: '#dc2626', padding: '10px 14px', borderRadius: '12px', fontSize: '12px', fontWeight: 600, marginBottom: '16px' }}>
            ⚠️ {errorMsg}
          </div>
        )}

        {profilePassSuccessMsg && (
          <div style={{ background: '#ecfdf5', border: '1px solid #6ee7b7', color: '#047857', padding: '10px 14px', borderRadius: '12px', fontSize: '12px', fontWeight: 600, marginBottom: '16px' }}>
            {profilePassSuccessMsg}
          </div>
        )}

        {/* Target Password Prompt Modal Card if user has a password */}
        {targetUserForLogin ? (
          <form onSubmit={handleSwitchSubmit} style={{ background: '#f8fafc', padding: '20px', borderRadius: '16px', border: '2px solid #6366f1', marginBottom: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <div style={{ width: '36px', height: '36px', borderRadius: '10px', background: targetUserForLogin.badgeColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px' }}>
                {targetUserForLogin.avatarIcon}
              </div>
              <div>
                <div style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a' }}>
                  Enter Password for {targetUserForLogin.name}
                </div>
                <div style={{ fontSize: '11px', color: '#64748b' }}>
                  🔒 Password verification required to switch to this profile
                </div>
              </div>
            </div>

            <div style={{ position: 'relative', marginBottom: '14px' }}>
              <input
                type={showSwitchPassword ? 'text' : 'password'}
                placeholder={`Enter ${targetUserForLogin.name}'s password...`}
                value={switchPassword}
                onChange={(e) => setSwitchPassword(e.target.value)}
                style={{ width: '100%', padding: '10px 40px 10px 12px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
                autoFocus
                required
              />
              <button
                type="button"
                onClick={() => setShowSwitchPassword(!showSwitchPassword)}
                style={{ position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }}
              >
                {showSwitchPassword ? 'Hide' : 'Show'}
              </button>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="submit"
                style={{ flex: 1, background: '#6366f1', color: '#ffffff', border: 'none', padding: '10px', borderRadius: '10px', fontWeight: 700, fontSize: '13px', cursor: 'pointer' }}
              >
                Unlock & Switch Account
              </button>
              <button
                type="button"
                onClick={() => { setTargetUserForLogin(null); setErrorMsg(null); }}
                style={{ background: '#e2e8f0', color: '#475569', border: 'none', padding: '10px 16px', borderRadius: '10px', fontWeight: 600, fontSize: '13px', cursor: 'pointer' }}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          /* User Account List */
          <div style={{ marginBottom: '20px' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '10px' }}>
              Select Active User Account
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '240px', overflowY: 'auto' }}>
              {allUsers.map((user) => {
                const isSelected = activeUser.id === user.id;

                return (
                  <div
                    key={user.id}
                    onClick={() => handleSelectUser(user)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '12px 16px',
                      borderRadius: '16px',
                      background: isSelected ? '#f8fafc' : '#ffffff',
                      border: isSelected ? '2px solid #6366f1' : '1px solid #e2e8f0',
                      cursor: isSelected ? 'default' : 'pointer',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{ width: '38px', height: '38px', borderRadius: '12px', background: user.badgeColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', color: '#ffffff' }}>
                        {user.avatarIcon}
                      </div>
                      <div>
                        <div style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a', display: 'flex', alignItems: 'center', gap: '6px' }}>
                          {user.name}
                          {user.hasPassword && (
                            <span style={{ fontSize: '10px', background: 'rgba(99, 102, 241, 0.15)', color: '#6366f1', padding: '1px 6px', borderRadius: '6px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '2px' }}>
                              <Lock size={10} /> Password Protected
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '11px', color: '#64748b' }}>{user.role}</div>
                      </div>
                    </div>

                    {isSelected ? (
                      <div style={{ background: '#6366f1', color: '#ffffff', padding: '4px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Check size={12} /> Active
                      </div>
                    ) : (
                      <div style={{ background: '#f1f5f9', color: '#475569', padding: '4px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 600 }}>
                        {user.hasPassword ? '🔒 Enter Password' : 'Switch Workspace'}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Lock / Password Setting for Active Profile */}
        {!showSetPassForm ? (
          <div style={{ marginBottom: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f8fafc', padding: '10px 14px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
            <div style={{ fontSize: '12px', color: '#475569', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Lock size={14} color="#6366f1" />
              <span>Current Profile: <strong>{activeUser.name}</strong></span>
            </div>
            <button
              type="button"
              onClick={() => setShowSetPassForm(true)}
              style={{ background: '#0f172a', color: '#ffffff', border: 'none', padding: '5px 12px', borderRadius: '8px', fontSize: '11px', fontWeight: 700, cursor: 'pointer' }}
            >
              🔒 Set / Update Profile Password
            </button>
          </div>
        ) : (
          <form onSubmit={handleSetProfilePassword} style={{ background: '#f8fafc', padding: '14px', borderRadius: '14px', border: '1px solid #cbd5e1', marginBottom: '14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: '#0f172a' }}>
              Set Password for '{activeUser.name}'
            </div>
            <input
              type="password"
              placeholder="Enter new profile password..."
              value={profileNewPassword}
              onChange={(e) => setProfileNewPassword(e.target.value)}
              style={{ width: '100%', padding: '8px 12px', borderRadius: '8px', border: '1px solid #cbd5e1', fontSize: '12px' }}
              required
            />
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="submit"
                style={{ flex: 1, background: '#0f172a', color: '#ffffff', border: 'none', padding: '8px', borderRadius: '8px', fontWeight: 700, fontSize: '12px', cursor: 'pointer' }}
              >
                Save Profile Password
              </button>
              <button
                type="button"
                onClick={() => setShowSetPassForm(false)}
                style={{ background: '#e2e8f0', color: '#475569', border: 'none', padding: '8px 12px', borderRadius: '8px', fontWeight: 600, fontSize: '12px', cursor: 'pointer' }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Create New User Form Toggle */}
        {!showCreateForm ? (
          <button
            onClick={() => setShowCreateForm(true)}
            style={{
              width: '100%',
              background: '#f8fafc',
              border: '1px dashed #cbd5e1',
              color: '#475569',
              padding: '12px',
              borderRadius: '14px',
              fontWeight: 600,
              fontSize: '13px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              cursor: 'pointer'
            }}
          >
            <UserPlus size={16} /> Create New User Workspace Profile
          </button>
        ) : (
          <form onSubmit={handleCreateUser} style={{ background: '#f8fafc', padding: '16px', borderRadius: '16px', border: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>Add New User Workspace Profile</div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Choose Avatar Icon</label>
              <div style={{ display: 'flex', gap: '8px', overflowX: 'auto' }}>
                {AVATAR_ICONS.map((icon) => (
                  <button
                    type="button"
                    key={icon}
                    onClick={() => setNewAvatarIcon(icon)}
                    style={{
                      background: newAvatarIcon === icon ? '#e0e7ff' : '#ffffff',
                      border: newAvatarIcon === icon ? '2px solid #6366f1' : '1px solid #cbd5e1',
                      borderRadius: '10px',
                      padding: '6px 10px',
                      fontSize: '18px',
                      cursor: 'pointer'
                    }}
                  >
                    {icon}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>User / Workspace Name</label>
              <input
                type="text"
                placeholder="e.g. Alice Workspace"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
                required
              />
            </div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Role / Description</label>
              <input
                type="text"
                placeholder="e.g. Lead Researcher"
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
              />
            </div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Access Password (Optional)</label>
              <input
                type="password"
                placeholder="Set optional password for this profile..."
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
              <button
                type="submit"
                style={{ flex: 1, background: '#6366f1', color: '#ffffff', border: 'none', padding: '10px', borderRadius: '10px', fontWeight: 700, fontSize: '13px', cursor: 'pointer' }}
              >
                Create Account & Switch
              </button>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                style={{ background: '#e2e8f0', color: '#475569', border: 'none', padding: '10px 16px', borderRadius: '10px', fontWeight: 600, fontSize: '13px', cursor: 'pointer' }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        <div style={{ marginTop: '20px', padding: '12px', borderRadius: '12px', background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.2)', fontSize: '11px', color: '#4f46e5', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Shield size={14} />
          <span>Active User: <strong>{activeUser.name}</strong> ({activeUser.id}). Custom models and voice chats are strictly private to this user!</span>
        </div>
      </div>
    </div>
  );
};
